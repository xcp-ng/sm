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

from xcp_storage.utils.service import (
    disable_and_stop_service,
    enable_and_start_service,
    is_service_active,
)

# ==============================================================================

LINSTOR_SATELLITE_PORT_PLAIN = 3366
LINSTOR_SATELLITE_PORT_SSL = 3367

# ------------------------------------------------------------------------------

_SERVICE_LINSTOR_SATELLITE = "linstor-satellite"

# ------------------------------------------------------------------------------

def is_satellite_running() -> bool:
    return is_service_active(_SERVICE_LINSTOR_SATELLITE)

def enable_and_start_satellite() -> None:
    enable_and_start_service(_SERVICE_LINSTOR_SATELLITE)

def disable_and_stop_satellite() -> None:
    disable_and_stop_service(_SERVICE_LINSTOR_SATELLITE)
