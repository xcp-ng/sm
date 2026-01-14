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
import json
from pathlib import Path
import re

import xcp_storage.log as log
from xcp_storage.utils.process import (
    get_process_cmdline,
    run_command,
)

from xcp_storage.typing import (
    Any,
    Dict,
    Iterator,
    List,
    override,
)

# ==============================================================================

DRBD_BY_RES_PATH = "/dev/drbd/by-res/"

# ------------------------------------------------------------------------------

_EXEC_PATH_DRBDSETUP = "/usr/sbin/drbdsetup"

_REGEX_DRBD_OPENER_LINE = re.compile(r"(.*)\s+([0-9]+)\s+([0-9]+)")

# ------------------------------------------------------------------------------

def build_drbd_path(resource_name: str, volume_number: int) -> str:
    return f"{DRBD_BY_RES_PATH}{resource_name}/{volume_number}"

def get_drbd_name_from_path(path: str) -> str:
    # Assume that we have a path like this:
    # - "/dev/drbd/by-res/xcp-volume-<UUID>/0"
    # - "../xcp-volume-<UUID>/0"
    if path.startswith(DRBD_BY_RES_PATH):
        prefix_len = len(DRBD_BY_RES_PATH)
    elif path.startswith("../"):
        prefix_len = 3
    else:
        return ""

    res_name_end = path.find("/", prefix_len)
    if res_name_end == -1:
        return ""

    return path[prefix_len:res_name_end]

# ------------------------------------------------------------------------------

@contextlib.contextmanager
def _handle_drbd_json_error() -> Iterator[None]:
    try:
        yield
    except KeyError as e:
        log.error(
            f"The key `{e}` could not be found in the DRBD configuration. The JSON format may have changed.",
            exc_info=True
        )
    except Exception as e:
        log.error(f"Failed to parse DRBD configuration: `{e}`. The JSON format may have changed.", exc_info=True)

def _get_drbd_status(resource_name: str) -> Dict[str, Any]:
    try:
        stdout, _stderr, ret_code = run_command([
            _EXEC_PATH_DRBDSETUP, "status", resource_name, "--json"
        ], simple=False)
        if ret_code != 0:
             return {}
    except Exception as e:
        log.error(f"Failed to get DRBD status: `{e}`.")
        return {}

    try:
        status = json.loads(stdout)
    except Exception as e:
        log.error(f"Failed to read DRBD status as JSON: `{e}`.")
        return {}

    with _handle_drbd_json_error():
        return status[0]
    return {}

# ------------------------------------------------------------------------------

def get_drbd_connection_address(resource_name: str, node_name: str) -> str:
    status = _get_drbd_status(resource_name)
    if not status:
        return ""

    with _handle_drbd_json_error():
        for connection in status["connections"]:
            if connection["name"] == node_name:
                return connection["paths"][0]["remote_host"]["address"]
    return ""

def get_drbd_primary_address(resource_name: str) -> str:
    status = _get_drbd_status(resource_name)
    if not status:
        return ""

    with _handle_drbd_json_error():
        if status["role"] == "Primary":
            return status["connections"][0]["paths"][0]["this_host"]["address"]

        for connection in status["connections"]:
            if connection["peer-role"] == "Primary":
                return connection["paths"][0]["remote_host"]["address"]

    return ""

# ------------------------------------------------------------------------------

class DrbdOpeners:
    # The duration is expressed in milliseconds.
    def __init__(self, pid: int, process_name: str, cmdline: List[str], open_duration: int) -> None:
        self.pid = pid
        self.process_name = process_name
        self.cmdline = cmdline
        self.open_duration = open_duration

    @override
    def __repr__(self) -> str:
        return f"DrbdOpeners({self.pid}, {self.process_name}, {self.cmdline}, {self.open_duration})"

def get_drbd_local_openers(resource_name: str, volume_number: int) -> List[DrbdOpeners]:
    assert resource_name, "Cannot get DRBD openers without resource name."

    path = Path(f"/sys/kernel/debug/drbd/resources/{resource_name}/volumes/{volume_number}/openers")
    try:
        lines = path.read_text().splitlines()
    except Exception as e:
        # The resource is probably available not on this node.
        log.info(f"Unable to get DRBD openers of volume `{resource_name}/{volume_number}`: `{e}`.")
        return []

    drbd_openers = []
    for line in lines:
        match = _REGEX_DRBD_OPENER_LINE.match(line)
        if not match:
            log.warning(f"Unable to parse DRBD opener line with: `{line}`.")
            continue

        groups = match.groups()
        pid = int(groups[1])
        drbd_openers.append(DrbdOpeners(
            pid=pid,
            process_name=groups[0],
            # Note: `cmdline`` is be empty for `mount` calls. Logic the PID is dead.
            cmdline=get_process_cmdline(pid),
            open_duration=int(groups[2])
        ))

    return drbd_openers

# ------------------------------------------------------------------------------

def demote_drbd(resource_name: str) -> bool:
    try:
        _stdout, stderr, ret_code = run_command([_EXEC_PATH_DRBDSETUP, "secondary", resource_name], simple=False)
        if not ret_code:
            return True
        log.error(f"Failed to demote DRBD resource `{resource_name}`: `{stderr}`.")
    except Exception as e:
        log.error(f"Failed to demote DRBD resource `{resource_name}`: `{e}`.")
    return False
