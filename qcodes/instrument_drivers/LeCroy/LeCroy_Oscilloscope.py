import logging
import binascii

import numpy as np
from pyvisa.errors import VisaIOError
from functools import partial

from qcodes import VisaInstrument, validators as vals
from qcodes import InstrumentChannel, ChannelList
from qcodes import ArrayParameter, MultiParameter, ManualParameter
from qcodes.utils.validators import Enum, Numbers


log = logging.getLogger(__name__)


class TraceNotReady(Exception):
    pass


class ScopeArray(ArrayParameter):
    """
        Array parameter holding the acquisition data.
    """
    def __init__(self, name, instrument, channel):
        super().__init__(name=name,
                         shape=(5001,),
                         label='Voltage',
                         unit='V ',
                         setpoint_names=('Time', ),
                         setpoint_labels=('Time', ),
                         setpoint_units=('s',),
                         docstring='holds an array from scope')
        self.channel = channel
        self._instrument = instrument

    def calc_set_points(self):
        #message = self._instrument.ask('C{}:INSPECT? WAVEDESC'.format(self.channel)) #gives all the info .split('\r\n')
        xstart = self._instrument.ask("VBS? 'Return=app.Acquisition.Channels(\"C{}\")".format(self.channel) + ".Out.Result.HorizontalOffset'")
        xinc = self._instrument.ask("VBS? 'Return=app.Acquisition.Channels(\"C{}\")".format(self.channel) + ".Out.Result.HorizontalPerStep'")
        no_of_points = self._instrument.ask('MSIZ?')
        no_of_points = float(no_of_points) +2
        no_of_points = int(no_of_points)
        xdata = np.linspace(float(xstart), float(no_of_points) * float(xinc) + float(xstart), float(no_of_points))
        return xdata, no_of_points


    def prepare_curvedata(self):
        """
        Prepare the scope for returning curve data
        """
        xdata, no_of_points = self.calc_set_points()
        self.setpoints = (tuple(xdata), )
        self.shape = (no_of_points, )

        self._instrument._parent.trace_ready = True


    def get(self):
        if not self._instrument._parent.trace_ready:
            raise TraceNotReady('Please run prepare_curvedata to prepare '
                                'the scope for giving a trace.')
        
        # get channel data
        wave = self._curveasker(self.channel)
        
        # get sclaes
        yoff = float(self._instrument.ask("VBS? 'Return=app.Acquisition.Channels(\"C{}\")".format(self.channel) + ".Out.Result.VerticalOffset'"))

        ymult = float(self._instrument.ask("VBS? 'Return=app.Acquisition.Channels(\"C{}\")".format(self.channel) + ".Out.Result.VerticalPerStep'"))
              
        # scale and return data
        ydata = wave*ymult+yoff
        return ydata


    def _curveasker(self, ch):
        # clear sweep
        self._instrument._parent.clsw()
        # trigger as many single events as averages 
        for i in range(self._instrument.average()):
            self._instrument._parent.write('TRMD SINGLE')
            self._instrument._parent.wait()
        values = None
        
        try:
            # get the waveform in binary 16bit form
            values = self._instrument._parent.visa_handle.query_binary_values('C{}:WAVEFORM? DAT1'.format(ch,'{}'), datatype='h', is_big_endian=False)# h is 16bit
        except ValueError:
            # in case of problems with receiving the data try again
            self._instrument._parent.clear_message_queue()
            values = self._instrument._parent.visa_handle.query_binary_values('C{}:WAVEFORM? DAT1'.format(ch,'{}'), datatype='h', is_big_endian=False)# h is 16bit
        # return to autotrigger
        self._instrument._parent.write('TRMD AUTO')
        return np.array(values)


class LCRChannel(InstrumentChannel):
    """
        Insturment channel for acquisition of time series data
    """
    def __init__(self, parent, name, channel):
        super().__init__(parent, name)

        self.add_parameter('scale',
                           label='Channel {} Scale'.format(channel),
                           unit='V/div',
                           get_cmd='C{}: Volt_DIV?'.format(channel),
                           set_cmd='C{}: Volt_DIV {}'.format(channel, '{}'),
                           get_parser=float
                           )
        
        self.add_parameter('position',
                           label='Channel {} Position'.format(channel),
                           unit='div',
                           get_cmd='CH{}:POSition?'.format(channel),
                           set_cmd='CH{}:POSition {}'.format(channel, '{}'),
                           get_parser=float
                           )
        
        self.add_parameter('curvedata',
                           channel=channel,
                           parameter_class=ScopeArray,
                           )
        
        self.add_parameter('average',
                           label='Channel {} averaging'.format(channel),
                           set_cmd="VBS 'app.Acquisition.C{}.AverageSweeps={}'".format(channel, '{}'),
                           get_cmd="VBS? 'Return=app.Acquisition.C{}.AverageSweeps'".format(channel),
                           get_parser=int
                           )
 


class LCR(VisaInstrument):
    """
    This is the QCoDeS driver for LeCroy Oscilloscopes based on the TPS2012 driver.
    
    Tested with:
        * LECROY HDO4054A, using USB or ETH
        * WR44XI-A, using ETH (select LXI/VXII not TCPIP/VCIP on instrument)
        
    Might work with others.
    
    Functionality:
        * Transfer time and selected channel data from screen 
        * Remotely trigger set averages and clear sweeps
        
    More functionality could be added.
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
        self.connect_message()
        # Scope trace boolean
        self.trace_ready = False

        # functions

        self.add_function('force_trigger',
                          call_cmd='ARM',
                          docstring='Force trigger event')
        self.add_function('clsw',
                           docstring='Clear Sweeps',
                           call_cmd='CLSW',
                           )          
        self.add_function('wait',
                           docstring='Wait to finish acquisition',
                           call_cmd='WAIT'
                           )          
        self.add_function('wai',
                           docstring='Wait to finish acquisition',
                           call_cmd='*WAI'
                           )     

        
        # general parameters
        self.add_parameter('trigger_type',
                           label='Type of the trigger',
                           get_cmd='TRMD?',
                           set_cmd='TRMD {}',
                           vals=vals.Enum('AUTO', 'NORMAL', 'SINGLE')
                           )
        self.add_parameter('time_scale',
                           label='Time scale',
                           unit='s',
                           get_cmd="VBS? 'return=app.Acquisition.Horizontal.HorScale'",
                           set_cmd="VBS 'app.Acquisition.Horizontal.HorScale={}'",
                           get_parser=float)
        self.add_parameter('time_offset',
                           label='Time scale',
                           unit='s',
                           get_cmd="VBS? 'return=app.Acquisition.Horizontal.HorOffset'",
                           set_cmd="VBS 'app.Acquisition.Horizontal.HorOffset={}'",
                           get_parser=float) 
        self.add_parameter('samples',
                           set_cmd = "MSIZ {}".format({}),
                           get_cmd = "MSIZ?"
                           )
           
         
        
        # channel-specific parameters
        channels = ChannelList(self, "ScopeChannels", LCRChannel, snapshotable=False)
        for ch_num in range(1, 5):
            ch_name = "ch{}".format(ch_num)
            channel = LCRChannel(self, ch_name, ch_num)
            channels.append(channel)
            self.add_submodule(ch_name, channel)
        channels.lock()
        self.add_submodule("channels", channels)
        
        # Necessary settings for parsing the binary curve data
        self.visa_handle.encoding = 'latin-1'
        self.visa_handle.read_termination='\n'
        log.info('Set VISA encoding to latin-1')
        self.write('COMM_HEADER OFF')
        log.info('Set Encoding to WORD BIN without header')
        self.write('COMM_FORMAT OFF,WORD,BIN')
        
        
       


    ##################################################
    # METHODS FOR THE USER                           #
    ##################################################

    def clear_message_queue(self, verbose=False):
        """
        Function to clear up (flush) the VISA message queue of the AWG
        instrument. Reads all messages in the the queue.

        Args:
            verbose (Bool): If True, the read messages are printed.
                Default: False.
        """
        original_timeout = self.visa_handle.timeout
        self.visa_handle.timeout = 5000  # 1 second as VISA counts in ms
        gotexception = False
        while not gotexception:
            try:
                message = self.visa_handle.read()
                if verbose:
                    print(message)
            except VisaIOError:
                gotexception = True
        self.visa_handle.timeout = original_timeout