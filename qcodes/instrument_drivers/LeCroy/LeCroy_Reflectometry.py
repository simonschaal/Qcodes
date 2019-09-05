import logging
import binascii

import numpy as np
from pyvisa.errors import VisaIOError
from functools import partial

from qcodes import VisaInstrument, validators as vals
from qcodes import InstrumentChannel, ChannelList
from qcodes import ArrayParameter, MultiParameter, ManualParameter
from qcodes.utils.validators import Enum, Numbers

import .LeCroyOscilloscope 

log = logging.getLogger(__name__)


class TraceNotReady(Exception):
    pass



class RFTrace(MultiParameter):
    """
        Multiparameter acquiring the I and Q data from two oscilloscope channels connected to IQ mixer and calculating magnitude and phase.
    """
    def __init__(self, name, instrument):
        super().__init__(name=name,
                         names=('I', 'Q', 'magnitude', 'phase'),
                         shapes=( (),(),(),() ),
                         labels=('I', 'Q', 'Magnitude', 'Phase'),
                         units=('V','V','V', 'Deg'),
                         )

        self.setpoint_names = (('Sweep',), ('Sweep',), ('Sweep',), ('Sweep',))
        self.setpoint_units=(('V',), ('V',), ('V',), ('V',))
        self._instrument = instrument


    def calc_set_points(self):
        # based on awg frequency and time increment of oscilloscope return no of points and voltage data array
        xstart = float(self._instrument._parent.ask("VBS? 'Return=app.Acquisition.Channels(\"C1\").Out.Result.HorizontalOffset'"))
        xinc = float(self._instrument._parent.ask("VBS? 'Return=app.Acquisition.Channels(\"C1\").Out.Result.HorizontalPerStep'"))
        no_of_points = int(self._instrument._parent.ask("VBS? 'Return=app.Acquisition.C1.Out.Result.Samples'"))
        if not self._instrument.frequency():
            raise TraceNotReady('Please enter rf frequency and averages.')
        # only capture ramp up of the triangle
        cut_rf = int(1/(2.*self._instrument.frequency())/xinc)
        #xdata = tuple(np.linspace(xstart, float(cut_rf) * xinc + xstart,cut_rf ))
        if not self._instrument.start():
            raise TraceNotReady('Please enter rf sweep start and end voltage.')
        vdata = tuple(np.linspace(self._instrument.start(), self._instrument.end(),cut_rf))
        return vdata, cut_rf
    

    def prepare_curvedata(self, channels=[1,3]):
        """
        Prepare the scope for returning curve data
        """
        # save channels
        self._I_ch=1
        self._Q_ch=3
        xdata, no_of_points = self.calc_set_points()
        self.setpoints = ((xdata, ),(xdata, ),(xdata, ),(xdata, ))
        self.shapes = ((no_of_points, ),(no_of_points, ),(no_of_points, ),(no_of_points, ))
        self._instrument._parent.trace_ready = True
        


        
    def get(self):
        if not self._instrument._parent.trace_ready:
            raise TraceNotReady('Please run prepare_curvedata to prepare '
                                'the scope for giving a trace.')
        
        self._instrument._parent.timeout(5+5*self._instrument.average()/50)
        self._instrument._parent.channels[self._I_ch-1].average(self._instrument.average())
        self._instrument._parent.channels[self._Q_ch-1].average(self._instrument.average())
        self._instrument._parent.clsw()
        for i in range(self._instrument.average()):
            self._instrument._parent.write('TRMD SINGLE')
            self._instrument._parent.wait()
        
        I=None
        Q=None
        
        try:
            I = np.array(self._instrument._parent.visa_handle.query_binary_values('C%d:WAVEFORM? DAT1'%self._I_ch, datatype='h', is_big_endian=False))# h is 16bit
            self._instrument._parent.write('*WAI')
            Q = np.array(self._instrument._parent.visa_handle.query_binary_values('C%d:WAVEFORM? DAT1'%self._Q_ch, datatype='h', is_big_endian=False))# h is 16bit  
        except ValueError:
            self._instrument._parent.clear_message_queue()
            I = np.array(self._instrument._parent.visa_handle.query_binary_values('C%d:WAVEFORM? DAT1'self._I_ch, datatype='h', is_big_endian=False))# h is 16bit
            self._instrument._parent.write('*WAI')
            self._instrument._parent.clear_message_queue()
            Q = np.array(self._instrument._parent.visa_handle.query_binary_values('C%d:WAVEFORM? DAT1'self._Q_ch, datatype='h', is_big_endian=False))# h is 16bit  
            
        self._instrument._parent.write('TRMD AUTO')
        
        Ioff=None
        Imult=None
        Qoff=None
        Qmult=None
        
        try:
            Ioff = float(self._instrument._parent.ask("VBS? 'Return=app.Acquisition.Channels(\"C%d\").Out.Result.VerticalOffset'"%self._I_ch))
            Imult = float(self._instrument._parent.ask("VBS? 'Return=app.Acquisition.Channels(\"C%d\").Out.Result.VerticalPerStep'"%self._I_ch))   
            Qoff = float(self._instrument._parent.ask("VBS? 'Return=app.Acquisition.Channels(\"C%d\").Out.Result.VerticalOffset'"%self._Q_ch))
            Qmult = float(self._instrument._parent.ask("VBS? 'Return=app.Acquisition.Channels(\"C%d\").Out.Result.VerticalPerStep'"%self._Q_ch)) 			
        except ValueError:
            self._instrument._parent.clear_message_queue()
            Ioff = float(self._instrument._parent.ask("VBS? 'Return=app.Acquisition.Channels(\"C%d\").Out.Result.VerticalOffset'"%self._I_ch))
            self._instrument._parent.clear_message_queue()
            Imult = float(self._instrument._parent.ask("VBS? 'Return=app.Acquisition.Channels(\"C%d\").Out.Result.VerticalPerStep'"%self._I_ch)) 
            self._instrument._parent.clear_message_queue()
            Qoff = float(self._instrument._parent.ask("VBS? 'Return=app.Acquisition.Channels(\"C%d\").Out.Result.VerticalOffset'"%self._Q_ch))
            self._instrument._parent.clear_message_queue()
            Qmult = float(self._instrument._parent.ask("VBS? 'Return=app.Acquisition.Channels(\"C%d\").Out.Result.VerticalPerStep'"%self._Q_ch))
		
        I = I*Imult-Ioff 
        Q = Q*Qmult-Qoff

        phase=np.arctan2( (self._instrument.Q_DC()+Q), (self._instrument.I_DC()+I) )*180./np.pi
        mag=np.sqrt(I**2 + Q**2)
        
        return I[0:self.shapes[0][0]], Q[0:self.shapes[0][0]], mag[0:self.shapes[0][0]], phase[0:self.shapes[0][0]]

 
class Reflectometry(InstrumentChannel):
    """
        Instrument channel realising reflectometry measurements.
    """
    def __init__(self, parent, name):
        super().__init__(parent, name)

        self.add_parameter('frequency',
                           parameter_class=ManualParameter,
                           #initial_value=83.,
                           label='Sweep gate frequency',
                           unit='Hz',
                           vals=Numbers(10e-3, 10e6))
        self.add_parameter('start',
                           parameter_class=ManualParameter,
                           label='Sweep start voltage',
                           unit='V',
                           vals=Numbers(-10, 10))
        self.add_parameter('end',
                           parameter_class=ManualParameter,
                           label='Sweep end voltage',
                           unit='V',
                           vals=Numbers(-10, 10))  
        self.add_parameter('average',
                           parameter_class=ManualParameter,
                           label='Average',
                           vals=Numbers(1, 100000))  
        self.add_parameter('I_DC',
                           parameter_class=ManualParameter,
                           initial_value=0.,
                           label='I DC Offset for AC coupling',
                           vals=Numbers(- 100000, 100000))  
        self.add_parameter('Q_DC',
                           parameter_class=ManualParameter,
                           initial_value=0.,
                           label='Q DC Offset for AC coupling',
                           vals=Numbers(- 100000, 100000)) 
        
        # Acquisition
        self.add_parameter(name='curvedata',
                           parameter_class=RFTrace
                           )
        
    def setup_AWG(self, awg):
        """
            ramps the AWG to the desired setpoint
            make sure sweep rates are defined!
            calculate parameters
        """
        amp = self.end() - self.start()
        offset = self.start() + amp/2
        
        # 50 Ohms output vs high impedance at device
        if awg.load() < 51:
            offset = offset/2
            amp = amp/2      
        
        # ramp down and up to measurement config
        #awg.offset(0)
        awg.amplitude(0.01)
        awg.output_functions('TRI')
        awg.phase(-90)
        awg.frequency(self.frequency())
        awg.offset(offset)
        awg.amplitude(amp)
 


class LCR_Reflectometry(LCR):
    """
    Inherits from LeCroy Oscilloscopes and adds reflectometry functionality.
    """

    def __init__(self, name, address, timeout=180, **kwargs):
        """
        Initialises instrument.

        Args:
            name (str): Name of the instrument used by QCoDeS
        address (string): Instrument address as used by VISA
            timeout (float): visa timeout, in secs. long default (180)
              to accommodate large waveforms
        """

        super().__init__(name, address, timeout=timeout, **kwargs)
        
        self.add_submodule('reflectometry', Reflectometry(self, 'reflectometry'))
