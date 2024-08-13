from typing import TYPE_CHECKING

from . import N52xx

if TYPE_CHECKING:
    from typing_extensions import Unpack

    from qcodes.instrument import VisaInstrumentKWArgs


class KeysightN5232B(N52xx.KeysightPNABase):
    def __init__(
        self, name: str, address: str, **kwargs: "Unpack[VisaInstrumentKWArgs]"
    ):
        super().__init__(
            name,
            address,
            min_freq=300e3,
            max_freq=20e9,
            min_power=-90,
            max_power=13,
            nports=4,
            **kwargs
        )
