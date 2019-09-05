import logging
from .ATS import AcquisitionController
import numpy as np
import qcodes.instrument_drivers.AlazarTech.ATS9462.acq_helpers as helpers
from qcodes.instrument.parameter import MultiParameter, ManualParameter
from qcodes.utils.validators import Numbers, Enum


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
        super().__init__(name=name, names=('I', 'Q', 'magnitude', 'phase'), shapes=( (),(),(),() ))
        self._instrument = instrument
        self.acquisition_kwargs = {}
        self.labels = ('I', 'Q', 'Magnitude', 'Phase')
        #self.full_names = ('Magnitude', 'Phase', 'I', 'Q')
        self.units = ('V','V', 'V', 'Deg')
        self.setpoint_names = (('Sweep',), ('Sweep',), ('Sweep',), ('Sweep',))

    def setup_acquisition(self, records_per_buffer=1, buffers_per_acquisition=1, allocated_buffers=1):
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
                timeout_ticks=(1e-6 / 10e-6 + 0.5),#wait 1us for trigger, then auto trigger
                aux_io_mode='AUX_OUT_TRIGGER'
        )
        
        sweep_time=self._instrument.integration()
        num_samples=int(self._instrument._get_alazar().samples_divisor*np.ceil(sweep_time*self._instrument.sample_rate()/self._instrument._get_alazar().samples_divisor))# needs to be multiple of 128
        timeout=100*self._instrument.averages()+4000 #account for longer timeout when averaging

        self._instrument.update_acquisition_kwargs(#mode='NPT',
                                              samples_per_record=num_samples,
                                              records_per_buffer=record_per_buffer,#averages
                                              buffers_per_acquisition=buffers_per_acquisition,
                                              allocated_buffers=allocated_buffers,
                                              buffer_timeout=timeout
                                              )
        
        f = tuple(np.linspace(self._instrument.start(), self._instrument.end(), num=num_samples))
        self.setpoints = ((f,), (f,), (f,), (f,))
        self.shapes = ((num_samples,), (num_samples,), (num_samples,), (num_samples,))

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
        I, Q = np.average(I), np.average(Q) #average over integration time
        phase=np.arctan( Q / I )*180./np.pi
        mag=np.sqrt(I**2 + Q**2)
        #self._save_val((I,Q))
        return I, Q, mag, phase


class VNA_Acquisition_Controller(AcquisitionController):
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
        # make a call to the parent class and by extension,
        # create the parameter structure of this class
        super().__init__(name, alazar_name, **kwargs)

        self.add_parameter(name='acquisition',
                           parameter_class=IQMagPhase)
        self.add_parameter('integration',
                           parameter_class=ManualParameter,
                           initial_value=10e-3.,
                           label='Integration time',
                           unit='s',
                           vals=Numbers(10e-9, 10e6)) 
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
        :return:
        """
        pass

    def handle_buffer(self, data):
        """
        Function which is called during the Alazar acquire each time a buffer
        is completed. In this acquistion controller these buffers are just
        added together (ie averaged)
        :return:
        """
        self.buffer += data

    def post_acquire(self):
        """
        Function which is called at the end of the Alazar acquire function to
        signal completion and trigger data processing. This acquisition
        controller has averaged over the buffers acquired so has one buffer of
        data which is splits into records and channels, averages over records
        and returns the samples for each channel.

        return:
        recordA: numpy array of channel A acquisition
        recordB: numpy array of channel B acquisition
        """

        # for ATS9360/ATS9626 samples are arranged in the buffer as follows:
        # S00A, S00B, S01A, S01B...S10A, S10B, S11A, S11B...
        # where SXYZ is record X, sample Y, channel Z.

        # this is not working !!!! mixing up buffers
        # break buffer up into records, averages over them and returns samples
        #records_per_acquisition = (self.buffers_per_acquisition *
                                   #self.records_per_buffer)

        #recA = np.zeros(self.samples_per_record)
        #for i in range(self.records_per_buffer):
        #    i0 = (i * self.samples_per_record * self.number_of_channels)
        #    i1 = (i0 + self.samples_per_record * self.number_of_channels)
        #    recA += self.buffer[i0:i1:self.number_of_channels]
        #recordA = np.uint16(recA / records_per_acquisition)

        #recB = np.zeros(self.samples_per_record)
        #for i in range(self.records_per_buffer):
        #    i0 = (i * self.samples_per_record * self.number_of_channels + 1)
        #    i1 = (i0 + self.samples_per_record * self.number_of_channels)
        #    recB += self.buffer[i0:i1:self.number_of_channels]
        #recordB = np.uint16(recB / records_per_acquisition)
        
        # copied from DFT controller from qcodes 0.12
        alazar = self._get_alazar()
        # average all records in a buffer
        records_per_acquisition = (1. * self.buffers_per_acquisition *
                                   self.records_per_buffer)
        recordA = np.zeros(self.samples_per_record)
        for i in range(self.records_per_buffer):
            i0 = i * self.samples_per_record
            i1 = i0 + self.samples_per_record
            recordA += self.buffer[i0:i1] / records_per_acquisition

        recordB = np.zeros(self.samples_per_record)
        for i in range(self.records_per_buffer):
            i0 = i * self.samples_per_record + len(self.buffer) // 2
            i1 = i0 + self.samples_per_record
            recordB += self.buffer[i0:i1] / records_per_acquisition

        # converts to volts if bits per sample is 12 (as ATS9360)
        bps = self.board_info['bits_per_sample']
        if bps == 12:
            volt_rec_A = helpers.sample_to_volt_u12(recordA, alazar.channel_range1.get(), bps)
            volt_rec_B = helpers.sample_to_volt_u12(recordB, alazar.channel_range1.get(), bps)
        if bps == 16:
            alazar = self._get_alazar()
            volt_rec_A = helpers.sample_to_volt_u16(recordA, alazar.channel_range1.get(), bps)
            volt_rec_B = helpers.sample_to_volt_u16(recordB, alazar.channel_range1.get(), bps)
        else:
            logging.warning('sample to volt conversion does not exist for bps '
                            '!= 12, raw samples centered on 0 and returned')
            volt_rec_A = recordA - np.mean(recordA)
            volt_rec_B = recordB - np.mean(recordB)

        return volt_rec_A, volt_rec_B
