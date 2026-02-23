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

import ssl

# Import API to ensure ApiDispatcher is exported with all public methods.
import xcp_storage.rpc.api  # noqa: F401
from xcp_storage.rpc.dispatcher import ApiDispatcher
from xcp_storage.utils.json.rpc.server import JsonRpcServer

from xcp_storage.typing import Optional

# ==============================================================================

class RpcApiServer(JsonRpcServer):
    def __init__(self, hostname: str, port: int, ssl_context: Optional[ssl.SSLContext] = None) -> None:
        super().__init__(ApiDispatcher, hostname, port, ssl_context)
