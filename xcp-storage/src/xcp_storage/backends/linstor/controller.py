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

from xcp_storage.backends.linstor.satellite import LINSTOR_SATELLITE_PORT_PLAIN, LINSTOR_SATELLITE_PORT_SSL
from xcp_storage.utils.process import run_command
from xcp_storage.utils.service import (
    is_service_active,
    restart_service,
    start_service,
    stop_service,
)

from xcp_storage.typing import List

# ==============================================================================

LINSTOR_CONTROLLER_PORT_PLAIN = 3370
LINSTOR_CONTROLLER_PORT_SSL = 3371

# ------------------------------------------------------------------------------

_SERVICE_LINSTOR_CONTROLLER = "linstor-controller"

# ------------------------------------------------------------------------------

def get_controller_addresses() -> List[str]:
    stdout = run_command([
        "/usr/sbin/ss", "-tnpH", "state", "established",
        f"( sport = :{LINSTOR_SATELLITE_PORT_PLAIN} or sport = :{LINSTOR_SATELLITE_PORT_SSL} )"
    ], expected_ret_code=0)
    return [
        line.split()[3].rsplit(":", 1)[0]
        for line in stdout.splitlines()
    ]

def get_controller_uri() -> str:
    # TODO: On caller side, check that an IP address from the current pool is returned.
    addresses = get_controller_addresses()
    return "linstor://" + addresses[0] if addresses else ""

# ------------------------------------------------------------------------------

def is_controller_running() -> bool:
    return is_service_active(_SERVICE_LINSTOR_CONTROLLER)

def start_controller() -> None:
    start_service(_SERVICE_LINSTOR_CONTROLLER)

def stop_controller() -> None:
    stop_service(_SERVICE_LINSTOR_CONTROLLER)

def restart_controller() -> None:
    restart_service(_SERVICE_LINSTOR_CONTROLLER)
