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

import inspect

from xcp_storage.typing import Any, Callable

# ==============================================================================

def is_callable_with(func: Callable[..., Any], *args: Any, **kwargs: Any) -> bool: # noqa: ANN401
    try:
        inspect.signature(func).bind(*args, **kwargs)
        return True
    except (TypeError, ValueError):
        return False
