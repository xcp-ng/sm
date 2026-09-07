import typing
from typing import *

# Manually importing `IO` for python 3.6 because it is not in `typing.__all__`
# and so, not imported by the statement above.
from typing import IO

if not hasattr(typing, 'override'):
    def override(method): # type: ignore
        try:
            # Set internal attr `__override__` like described in PEP 698.
            method.__override__ = True
        except (AttributeError, TypeError):
            pass
        return method

if not hasattr(typing, 'Never'):
    Never = None # type: ignore

if not hasattr(typing, 'Final'):
    Final = None # type: ignore

if not hasattr(typing, "Literal"):
    from typing_extensions import Literal  # noqa: F401, UP035
