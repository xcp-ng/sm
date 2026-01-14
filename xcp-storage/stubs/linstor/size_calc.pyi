from .errors import LinstorError as LinstorError
from _typeshed import Incomplete

class SizeCalc:
    _base_2: int
    _base_10: int
    UNIT_B: Incomplete
    UNIT_S: Incomplete
    UNIT_KiB: Incomplete
    UNIT_MiB: Incomplete
    UNIT_GiB: Incomplete
    UNIT_TiB: Incomplete
    UNIT_PiB: Incomplete
    UNIT_EiB: Incomplete
    UNIT_ZiB: Incomplete
    UNIT_YiB: Incomplete
    UNIT_kB: Incomplete
    UNIT_MB: Incomplete
    UNIT_GB: Incomplete
    UNIT_TB: Incomplete
    UNIT_PB: Incomplete
    UNIT_EB: Incomplete
    UNIT_ZB: Incomplete
    UNIT_YB: Incomplete
    UNITS_MAP: Incomplete
    UNITS_LIST_STR: Incomplete
    @classmethod
    def unit_to_str(cls, unit): ...
    @classmethod
    def parse_unit(cls, value): ...
    @classmethod
    def auto_convert(cls, value, unit_to): ...
    @classmethod
    def convert(cls, size, unit_in, unit_out): ...
    @classmethod
    def convert_round_up(cls, size, unit_in, unit_out): ...
    @classmethod
    def approximate_size_string(cls, size_kib): ...
