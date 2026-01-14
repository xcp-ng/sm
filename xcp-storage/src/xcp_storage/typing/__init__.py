#!/usr/bin/env python3
#
# Copyright (C) 2026  Vates SAS
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import contextlib
import typing
from typing import *  # noqa: F403

# ==============================================================================

# TODO: Remove all hacks for python 3.11.

if not hasattr(typing, "override"):
    def override(method): # type: ignore
        with contextlib.suppress(AttributeError, TypeError):
            # Set internal attr `__override__` like described in PEP 698.
            method.__override__ = True
        return method

if not hasattr(typing, "Never"):
    Never = None # type: ignore

if not hasattr(typing, "Literal"):
    from typing_extensions import Literal  # noqa: F401, UP035

if not hasattr(typing, "ParamSpec"):
    class _SubscriptableListMock(list):
        def __getitem__(self, _): # type: ignore
            return self
        def __getattr__(self, _): # type: ignore
            return self
        def __call__(self, *_args, **_kwargs): # type: ignore
            return self

    ParamSpec = _SubscriptableListMock() # type: ignore
    Concatenate = _SubscriptableListMock() # type: ignore
