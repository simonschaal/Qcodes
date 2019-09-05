import logging
from .ATS import AcquisitionController
import numpy as np
import qcodes.instrument_drivers.AlazarTech.ATS9462.acq_helpers as helpers
from qcodes.instrument.parameter import MultiParameter, ManualParameter
from qcodes.utils.validators import Numbers, Enum
"""
Requires two AWGs: 1st awg ch1 is fast x sweep. Ch2 is same frequency TTL for alazar trigger. external trigger of awgx needs to be connected to agwy. awgy is slow sweep.
Awgx is triggered through bus (pre_acquire) and awgy is trigger via awgx through eternal trigger. number of samples of alazra sets number of points for x sweep. nmber of records per acqusition sets number og points for y sweep
"""


class IQMagPhase(MultiParameter):
    """
    Hardware controlled parameter class for Alazar acquisition. To be used with
    Acquisition Controller (tested with ATS9626 board)

    Alazar Instrument 'acquire' returns a buffer of data each time a buffer is
    filled (channels * samples * records) which is processed by the
    post_acquire function of the Acquisition Controller and finally the
    processed result is returned when the SampleSweep parameter is called.

    :args:
    name: name for this parameter
    instrument: acquisition controller instrument this parameter belongs to
    """

    def __init__(self, name, instrument):
        super().__init__(name=name, names=('I', 'Q', 'magnitude', 'phase'), shapes=( (),(),(),() ) )
        self._instrument = instrument
        self.acquisition_kwargs = {}
        self.labels = ('I', 'Q', 'Magnitude', 'Phase')
        #self.full_names = ('Magnitude', 'Phase', 'I', 'Q')
        self.units = ('V','V', 'V', 'Deg')
        self.setpoint_names = (('Sweep Y','Sweep X'), ('Sweep Y','Sweep X'), ('Sweep Y','Sweep X'), ('Sweep Y','Sweep X'))

    def setup_sweep(self, buffers_per_acquisition=1, allocated_buffers=1):
        # define additional parameters as standard values in ats driver files to make it compatible with this
        self._instrument._get_alazar().config(
                clock_source='INTERNAL_CLOCK',
                sample_rate=self._instrument.sample_rate(),
                clock_edge='CLOCK_EDGE_RISING',
                decimation=0,
                coupling=[self._instrument.input_coupling(), self._instrument.input_coupling()],
                channel_range=[self._instrument.input_range(), self._instrument.input_range()], 
                impedance=[self._instrument.impedance(),self._instrument.impedance()],
                bwlimit=['DISABLED','DISABLED'],
                trigger_operation='TRIG_ENGINE_OP_J',
                trigger_engine1='TRIG_ENGINE_J',
                trigger_source1='EXTERNAL',
                trigger_slope1='TRIG_SLOPE_POSITIVE',
                trigger_level1=140,#128 means trigger above 0V
                trigger_engine2='TRIG_ENGINE_K',
                trigger_source2='DISABLE',
                trigger_slope2='TRIG_SLOPE_POSITIVE',
                trigger_level2=128,
                external_trigger_coupling='DC',
                external_trigger_range='ETR_5V',
                trigger_delay=0,
                timeout_ticks=1,
                aux_io_mode='AUX_OUT_TRIGGER'
        )
        

        timeout=100*self._instrument.y_npts()+4000 #account for longer timeout when averaging

        self._instrument.update_acquisition_kwargs(#mode='NPT',
                                              samples_per_record=self._instrument.x_npts(),
                                              records_per_buffer=self._instrument.y_npts(),
                                              buffers_per_acquisition=buffers_per_acquisition,
                                              allocated_buffers=allocated_buffers,
                                              buffer_timeout=timeout
                                              )
        
        self.shapes = ((self._instrument.y_npts(),self._instrument.x_npts()), (self._instrument.y_npts(),self._instrument.x_npts()), (self._instrument.y_npts(),self._instrument.x_npts()), (self._instrument.y_npts(),self._instrument.x_npts()))

    def get(self):
        """
        Gets the samples for channels A and B by calling acquire
        on the alazar (which in turn calls the processing functions of the
        aqcuisition controller before returning the reshaped data averaged
        over records and buffers)

        returns:
        recordA: numpy array of channel A acquisition
        recordB: numpy array of channel B acquisition
        """
        I, Q = self._instrument._get_alazar().acquire(
            acquisition_controller=self._instrument,
            **self.acquisition_kwargs)
        phase=np.arctan( Q / I )*180./np.pi
        mag=np.sqrt(I**2 + Q**2)
        #self._save_val((I,Q))
        return I, Q, mag, phase


class Reflectometry_Acquisition_Controller(AcquisitionController):
    """
    This class represents an acquisition controller. It is designed to be used
    primarily to check the function of the Alazar driver and returns the
    samples on channel A and channel B, averaging over recoirds and buffers
    I needs to be CHA and Q  needs to be CHB

    args:
    name: name for this acquisition_conroller as an instrument
    alazar_name: the name of the alazar instrument such that this controller
        can communicate with the Alazar
    **kwargs: kwargs are forwarded to the Instrument base class
    """

    def __init__(self, name, alazar_name, **kwargs):
        self.number_of_channels = 2
        self.awgx = None
        self.awgy = None
        
        # make a call to the parent class and by extension,
        # create the parameter structure of this class
        super().__init__(name, alazar_name, **kwargs)

        self.add_parameter(name='acquisition',
                           parameter_class=IQMagPhase)
        self.add_parameter('x_start',
                           parameter_class=ManualParameter,
                           label='Sweep x start voltage',
                           unit='V',
                           vals=Numbers(-10, 10))
        self.add_parameter('x_end',
                           parameter_class=ManualParameter,
                           label='Sweep x end voltage',
                           unit='V',
                           vals=Numbers(-10, 10))   
        self.add_parameter('x_npts',
                           parameter_class=ManualParameter,
                           label='Number of point x (needs to be multiple of 128)',
                           unit=None,
                           vals=Numbers(1, 10000))
        self.add_parameter('y_start',
                           parameter_class=ManualParameter,
                           label='Sweep x end voltage',
                           unit='V',
                           vals=Numbers(-10, 10))   
        self.add_parameter('y_end',
                           parameter_class=ManualParameter,
                           label='Sweep x end voltage',
                           unit='V',
                           vals=Numbers(-10, 10))   
        self.add_parameter('y_npts',
                           parameter_class=ManualParameter,
                           label='Number of point x',
                           unit=None,
                           vals=Numbers(1, 10000))
        self.add_parameter('sample_rate',
                           parameter_class=ManualParameter,
                           initial_value=500000.,
                           label='Sample rate',
                           unit=None,
                           vals=Numbers(1, 250e6))
        self.add_parameter('input_coupling',
                           parameter_class=ManualParameter,
                           initial_value='DC',
                           label='Coupling',
                           unit=None,
                           vals=Enum('DC', 'AC'))    
        self.add_parameter('input_range',
                           parameter_class=ManualParameter,
                           initial_value=2.,
                           label='Range',
                           unit=None,
                           vals=Enum(0.2, 0.4,
                                   0.8, 2., 4., 8, 16))  
        self.add_parameter('impedance',
                           parameter_class=ManualParameter,
                           initial_value=50,
                           label='Impedance',
                           unit=None,
                           vals=Enum(50, 1000000)) 
    def setup_AWG(self):
        # make sure sweep rates are defined!
        # calculate parameters

        # 50 Ohms output vs high capacitance to ground at device
        # the voltage at device is twice as large. e.g. use 500mV offset and 100mvpp to scan from -1.1 to -0.9V
        #offset = offset/2
        #amp = amp/2
        
        # ramp down and up to measurement config
        #awg.offset(0)
        
        if not self.awgx:
            print('AWG not defined!')
            pass
        
        # setup x fast ramp, burst with number of points we want for y (should be large), maybe switch to new 33500 driver and access channels: awgx,ch1 etc. few khz sweep freq is good, that means for 100 points few MS/s is good
        awgx.write('SOUR1:FUNC RAMP')
        awgx.write('OUTP1:LOAD INF')
        awgx.write('SOUR1:BURS:MODE TRIG')
        awgx.write('TRIG1:SOUR BUS')
        awgx.write('SOUR1:BURS:NCYC '+str(self.y_npts()))
        awgx.write('OUTP:TRIG ON')
        awgx.write('SOUR1:BURS:STAT ON')
        awgx.ch1.phase(-90)
        awgx.ch1.frequency(self.sample_rate()/self.x_npts())
        ampx = self.x_end() - self.x_start()
        offsetx = self.x_start() + ampx/2
        awgx.ch1.offset(offsetx)
        awgx.ch1.amplitude(ampx)
        
        awgx.write('SOUR2:FUNC SQU')
        awgx.write('OUTP2:LOAD 50')
        awgx.write('SOUR2:BURS:MODE TRIG')
        awgx.write('TRIG2:SOUR BUS')
        awgx.write('SOUR2:BURS:NCYC '+str(self.y_npts()))
        awgx.write('OUTP:TRIG ON')
        awgx.write('SOUR2:BURS:STAT ON')
        awgx.ch2.phase(-90)
        awgx.ch2.frequency(self.sample_rate()/self.x_npts())
        awgx.ch2.offset(210e-3)
        awgx.ch2.amplitude(400e-3)

        #setup y
        awgy.write('SOUR1:FUNC RAMP')
        awgy.write('OUTP1:LOAD INF')
        awgy.write('SOUR1:BURS:MODE TRIG')
        awgy.write('TRIG1:SOUR EXT')
        awgx.write('SOUR1:BURS:NCYC 1')
        awgx.write('OUTP:TRIG ON')
        awgx.write('SOUR1:BURS:STAT ON')
        awgx.ch1.phase(-90)
        awgx.ch1.frequency(awgx.ch1.frequency()*self.y_npts())
        ampy = self.y_end() - self.y_start()
        offsety = self.y_start() + ampy/2
        awgx.ch1.offset(offsety)
        awgx.ch1.amplitude(ampy)
        
        

    def update_acquisition_kwargs(self, **kwargs):
        """
        This method must be used to update the kwargs used for the acquisition
        with the alazar_driver.acquire
        :param kwargs:
        :return:
        """
        self.samples_per_record = kwargs['samples_per_record']
        self.acquisition.shapes = (
            (self.samples_per_record,), (self.samples_per_record,))
        self.acquisition.acquisition_kwargs.update(**kwargs)

    def pre_start_capture(self):
        """
        This function is run before capture. Then Alazar capture is started followed by running the pre_acquire function.
        See AcquisitionController
        :return:
        """
        alazar = self._get_alazar()
        if self.samples_per_record != alazar.samples_per_record.get():
            raise Exception('Instrument samples_per_record settings does '
                            'not match acq controller value, most likely '
                            'need to call update_acquisition_settings')
        self.records_per_buffer = alazar.records_per_buffer.get()
        self.buffers_per_acquisition = alazar.buffers_per_acquisition.get()
        self.board_info = alazar.get_idn()
        self.buffer = np.zeros(self.samples_per_record *
                               self.records_per_buffer *
                               self.number_of_channels)

    def pre_acquire(self):
        """
        See AcquisitionController
        Best place to trigger AWG 
        :return:
        """
        pass
        #self.awgx.write('*TRIG') # this somehow didnt work yet and I switched to continous trigger on awgx

    def handle_buffer(self, data):
        """
        Function which is called during the Alazar acquire each time a buffer
        is completed. In this acquistion controller these buffers are just
        added together (ie averaged)
        :return:
        """
        self.buffer += data
        # I could do *TRIG again and do averages

    def post_acquire(self):
        """
        Function which is called at the end of the Alazar acquire function to
        signal completion and trigger data processing. This acquisition
        controller has averaged over the buffers acquired so has one buffer of
        data which is splits into records and channels, averages over records
        and returns the samples for each channel.

        return:
        recordA: numpy 2d array of channel A acquisition
        recordB: numpy 2d array of channel B acquisition
        """

        
        # copied from DFT controller from qcodes 0.12
        alazar = self._get_alazar()
        bps = self.board_info['bits_per_sample']
        # average all records in a buffer
        records_per_acquisition = (1. * self.buffers_per_acquisition *
                                   self.records_per_buffer)
        recordA = np.zeros([self.y_npts(), self.x_npts()])
        for i in range(self.records_per_buffer):
            i0 = i * self.samples_per_record
            i1 = i0 + self.samples_per_record
            recordA[i] = helpers.sample_to_volt_u16(self.buffer[i0:i1], alazar.channel_range1.get(), bps)

        recordB = np.zeros([self.y_npts(), self.x_npts()])
        for i in range(self.records_per_buffer):
            i0 = i * self.samples_per_record + len(self.buffer) // 2
            i1 = i0 + self.samples_per_record
            recordB[i] = helpers.sample_to_volt_u16(self.buffer[i0:i1], alazar.channel_range2.get(), bps)


        return recordA, recordB
