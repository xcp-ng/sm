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

from xcp_storage.utils.process import CommandError, run_command

from xcp_storage.typing import (
    List,
    Optional,
)

# ==============================================================================

_EXEC_PATH_SYSTEMCTL = "/usr/bin/systemctl"

# ------------------------------------------------------------------------------

class ServiceError(Exception):
    def __init__(self, message: str, code: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code

# ------------------------------------------------------------------------------

def _run_service_command(service_name: str, action: List[str], *, quiet: bool = False) -> None:
    args = [_EXEC_PATH_SYSTEMCTL] + action
    args.append(service_name)
    try:
        run_command(args, expected_ret_code=0, quiet=quiet)
    except CommandError as e:
        raise ServiceError(e.reason, e.code) from None

# ------------------------------------------------------------------------------

def escape_service_instance(service_instance: str) -> str:
    # A quick reminder: An instance is the right part of a service after `@`.
    return service_instance.replace("-", "\\x2d")

# ------------------------------------------------------------------------------

def is_service_active(service_name: str) -> bool:
    try:
        _run_service_command(service_name, ["--quiet", "is-active"], quiet=True)
        return True
    except ServiceError:
        return False

def start_service(service_name: str) -> None:
    _run_service_command(service_name, ["start"])

def stop_service(service_name: str) -> None:
    _run_service_command(service_name, ["--quiet", "stop"])

def restart_service(service_name: str) -> None:
    _run_service_command(service_name, ["restart"])

def try_restart_service(service_name: str) -> None:
    _run_service_command(service_name, ["try-restart"])

def enable_and_start_service(service_name: str) -> None:
    _run_service_command(service_name, ["enable", "--now"])

def disable_and_stop_service(service_name: str) -> None:
    _run_service_command(service_name, ["disable", "--now"])

# ------------------------------------------------------------------------------

def reload_service_conf() -> None:
    try:
        run_command([_EXEC_PATH_SYSTEMCTL, "daemon-reload"], expected_ret_code=0)
    except CommandError as e:
        raise ServiceError(e.reason, e.code) from None
