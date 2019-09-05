from qcodes import Instrument
from qcodes.instrument.parameter import ManualParameter
from qcodes.utils.validators import Bool, Enum, Numbers

from qcodes.instrument.parameter import MultiParameter


class CurrentParameter(MultiParameter):
    """
    Amplified current measurement via an SR570 preamp and a measured voltage.

    To be used when you feed a current into an SR570, send the SR570's
    output voltage to a lockin or other voltage amplifier, and you have
    the voltage reading from that amplifier as a qcodes parameter.

    ``VoltageParameter.get()`` returns ``(voltage_raw, voltage)``

    Args:
        measured_param (Parameter): a gettable parameter returning the
            voltage read from the SR560 output.

        _ins (SR560): an SR560 instance where you manually
            maintain the present settings of the real SR560 amp.

            Note: it should be possible to use other voltage preamps, if they
            define parameters ``gain`` (V_out / V_in) and ``invert``
            (bool, output is inverted)

        name (str): the name of the current output. Default 'curr'.
            Also used as the name of the whole parameter.
    """
    def __init__(self, measured_param, c_amp_ins, name='current'):
        p_name = measured_param.name

        super().__init__(name=name, names=(p_name+'_raw', name), shapes=((),()))

        self._measured_param = measured_param
        self._instrument = c_amp_ins

        p_label = getattr(measured_param, 'label', None)
        p_unit = getattr(measured_param, 'unit', None)

        self.labels = (p_label, 'Current')
        self.units = (p_unit, 'A')

    def get(self):
        volt = self._measured_param.get()
        current_amp = (volt * self._instrument.sensitivity.get())

        if self._instrument.invert.get():
            volt_amp *= -1

        value = (volt, current_amp)
        self._save_val(value)
        return value


class SR570(Instrument):
    """
    This is the qcodes driver for the SR 570 Current-preamplifier.

    This is a virtual driver only and will not talk to your instrument.

    Note:
    - The ``cutoff_lo`` and ``cutoff_hi`` parameters will interact with
      each other on the instrument (hi cannot be <= lo) but this is not
      managed here, you must ensure yourself that both are correct whenever
      you change one of them.

    - ``gain`` has a vernier setting, which does not yield a well-defined
      output. We restrict this driver to only the predefined gain values.
    """
    def __init__(self, name, **kwargs):
        super().__init__(name, **kwargs)

        cutoffs = ['DC', 0.03, 0.1, 0.3, 1, 3, 10, 30, 100, 300, 1000,
                   3000, 10000, 30000, 100000, 300000, 1000000]

        self.add_parameter('cutoff_lo',
                           parameter_class=ManualParameter,
                           initial_value='DC',
                           label='High pass',
                           unit='Hz',
                           vals=Enum(*cutoffs))

        self.add_parameter('cutoff_hi',
                           parameter_class=ManualParameter,
                           initial_value=1e6,
                           label='Low pass',
                           unit='Hz',
                           vals=Enum(*cutoffs))

        self.add_parameter('invert',
                           parameter_class=ManualParameter,
                           initial_value=False,
                           label='Inverted output',
                           vals=Bool())

        self.add_parameter('sensitivity',
                           parameter_class=ManualParameter,
                           initial_value=100e-9,
                           label='Sensitivity',
                           unit=None,
                           vals=Numbers(1e-12, 500e-3))
        
        self.add_parameter('input_offset',
                           parameter_class=ManualParameter,
                           initial_value=1e-12,
                           label='Input offset',
                           unit=None,
                           vals=Numbers(-500e-3, 500e-3))
        
        self.add_parameter('bias_voltage',
                           parameter_class=ManualParameter,
                           initial_value='OFF',
                           label='Bias voltage',
                           unit=None,
                           vals=Enum('POS', 'NEG', 'OFF'))
        
        self.add_parameter('gain_mode',
                           parameter_class=ManualParameter,
                           initial_value='LOW NOISE',
                           label='Gain mode',
                           unit=None,
                           vals=Enum('LOW NOISE', 'HIGH BW', 'LOW DRIFT'))
    def get_idn(self):
        vendor = 'Stanford Research Systems'
        model = 'SR570'
        serial = None
        firmware = None

        return {'vendor': vendor, 'model': model,
                'serial': serial, 'firmware': firmware}
