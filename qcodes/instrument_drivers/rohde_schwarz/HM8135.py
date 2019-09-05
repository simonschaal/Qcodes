from qcodes import VisaInstrument, validators as vals


class RohdeSchwarz_HM8135(VisaInstrument):
    """
    This is the qcodes driver for the Rohde & Schwarz HM8135 signal generator
    Serial or USB interface tested
    termination needs to be \r
    read parser needs initial two chars to be thrown away
    """

    def __init__(self, name, address, **kwargs):
        super().__init__(name, address, terminator='\r', **kwargs)

        self.add_parameter(name='frequency',
                           label='Frequency',
                           unit='Hz',
                           get_cmd=':FREQ' + '?',
                           set_cmd=self.set_freq,#':FREQ' + ' {:.2f}',
                           get_parser=self.float_parse,
                           vals=vals.Numbers(1e6, 3e9))
        self.add_parameter(name='phase',
                           label='Phase',
                           unit='deg',
                           get_cmd=':PHAS' + '?',
                           set_cmd=':PHAS' + ' {}',
                           get_parser=self.float_parse,
                           vals=vals.Enum('INT', 'EXT'))
        self.add_parameter(name='power',
                           label='Power',
                           unit='dBm',
                           get_cmd='SOUR:POW' + '?',
                           set_cmd='SOUR:POW' + ' {:.2f}',
                           get_parser=self.float_parse,
                           vals=vals.Numbers(-120, 7))
        self.add_parameter('status',
                           get_cmd=':OUTP?',
                           set_cmd=':OUTP {}',
                           get_parser=self.int_parse,
                           val_mapping={'ON': 1, 'OFF': 0})

        self.add_function('reset', call_cmd='*RST')

        self.connect_message()
        
    def float_parse(self, string):
        return float(string.strip('\x11\x13').strip('\\x11\\x13'))
        
    def int_parse(self, string):
        return int(string.strip('\x11\x13'))
    def set_freq(self, val):
        self.write(':FREQ %s'%(val))
