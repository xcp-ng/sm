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

from xcp_storage.config.platform import DEFAULT_FIREWALL_INPUT_CHAIN
from xcp_storage.utils.process import CommandError, run_command

from xcp_storage.typing import (
    List,
    Optional,
    Tuple,
)

# ==============================================================================

_MAIN_FIREWALL_INPUT_CHAIN = "INPUT"

_EXEC_PATH_IPTABLES = "/usr/sbin/iptables"
_EXEC_PATH_SERVICE = "/usr/sbin/service"

_PROTOCOL_TCP = "tcp"

# ------------------------------------------------------------------------------

class IptablesError(Exception):
    def __init__(self, message: str, code: Optional[int] = None) -> None:
        super().__init__(message)
        self.code = code

# ------------------------------------------------------------------------------

def _save_iptables_changes() -> None:
    try:
        run_command([_EXEC_PATH_SERVICE, "iptables", "save"], expected_ret_code=0)
    except CommandError as e:
        raise IptablesError(f"Failed to save iptables changes: `{e.reason}`.", e.code) from None

# ------------------------------------------------------------------------------

def has_iptables_rule(rule: List[str]) -> bool:
    try:
        _stdout, _stderr, ret_code = run_command([_EXEC_PATH_IPTABLES, "-C"] + rule, simple=False)
        return not ret_code
    except CommandError as e:
        raise IptablesError(e.reason, e.code) from None

# ------------------------------------------------------------------------------

def _update_iptables_ports(protocol: str, str_ports: str, open_ports: bool, stateful: bool, chain: str) -> None:
    # 1. Check if the rule is present.
    rule = [chain, "-p", protocol]
    if stateful:
        rule += ["-m", "conntrack", "--ctstate", "NEW", "-m", protocol]
    rule += ["--dport", str_ports, "-j", "ACCEPT"]

    if open_ports == has_iptables_rule(rule):
        return

    # 2. Open or close.
    if open_ports:
        try:
            _stdout, _stderr, ret_code = run_command([_EXEC_PATH_IPTABLES, "-N", chain], simple=False)
            if not ret_code:
                # Create chain if necessary.
                run_command([_EXEC_PATH_IPTABLES, "-A", chain, "-j", "RETURN"], expected_ret_code=0)
                run_command([_EXEC_PATH_IPTABLES, "-I", _MAIN_FIREWALL_INPUT_CHAIN, "-j", chain], expected_ret_code=0)
            # Create rule.
            run_command([_EXEC_PATH_IPTABLES, "-I"] + rule, expected_ret_code=0)
        except CommandError as e:
            raise IptablesError(f"Failed to open {protocol.upper()} port(s): `{e.reason}`.", e.code) from None
    else:
        try:
            run_command([_EXEC_PATH_IPTABLES, "-D"] + rule, expected_ret_code=0)
        except CommandError as e:
            raise IptablesError(f"Failed to close {protocol.upper()} port(s): `{e.reason}`.", e.code) from None

    # 3. Save.
    _save_iptables_changes()

# ------------------------------------------------------------------------------

# Open/close TCP port using stateless or stateful rule.
#
# /!\ When opening or closing TCP ports using stateful rules, be aware of the Linux `conntrack` mechanism:
# it maintains a state database of all network connections (TCP, UDP, ...) passing through a machine.
# This is important for packet filtering, but there is a limitation:
# The kernel sets a maximum limit `nf_conntrack_max` based on available RAM.
# If this limit is reached, the system will log:
# `nf_conntrack: table full, dropping packets`
# and and start rejecting incoming/outgoing traffic...
#
# Even after a connection is closed, the kernel retains the entry in the table for a long period,
# 120 seconds for TCP.
#
# So it's important to avoid `conntrack` for specific case like DRBD protocol.
# For it, that's important to allow packets to pass even when the connection tracking table
# ran full temporarily because short-lived connections are the primary cause of table exhaustion
# AND because we can have this scenario with DRBD.

def update_iptables_tcp_port(
    port: int,
    *,
    open_port: bool,
    stateful: bool = True,
    chain: str = DEFAULT_FIREWALL_INPUT_CHAIN
) -> None:
    _update_iptables_ports(_PROTOCOL_TCP, str(port), open_port, stateful, chain)

def update_iptables_tcp_port_range(
    ports: Tuple[int, int],
    *,
    open_ports: bool,
    stateful: bool = True,
    chain: str = DEFAULT_FIREWALL_INPUT_CHAIN
) -> None:
    _update_iptables_ports(_PROTOCOL_TCP, f"{ports[0]}:{ports[1]}", open_ports, stateful, chain)
