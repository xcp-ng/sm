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

import time

from xcp_storage.typing import (
    Callable,
    TypeVar,
)

T = TypeVar("T")

# ==============================================================================

def wait_for_condition(function: Callable[[], T], timeout: float, interval: float) -> T:
    if timeout <= 0:
        return function()

    start_time = time.time()
    while True:
        result = function()
        if result or time.time() - start_time >= timeout:
            return result
        time.sleep(interval)
