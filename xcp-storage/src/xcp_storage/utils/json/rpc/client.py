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
import time
from types import TracebackType

import xcp_storage.log as log
from xcp_storage.utils.json import JsonDict, JsonList
from xcp_storage.utils.json.rpc import (
    JsonRpcRequest,
    JsonRpcResponse,
    JsonRpcResponseError,
    JsonValue,
)
from xcp_storage.utils.network.protocol import Protocol, ProtocolError
from xcp_storage.utils.network.protocol.xcp import XcpProtocol
from xcp_storage.utils.network.socket import SocketDisconnectedError
from xcp_storage.utils.network.tcp_client import TcpClient

from xcp_storage.typing import (
    Optional,
    Type,
    Union,
)

# ==============================================================================

_DEBUG_CLIENT = False

# ------------------------------------------------------------------------------

# Timeout for connect/call.
JSON_RPC_DEFAULT_TIMEOUT = 120.0

# Client timeout for send/receive.
JSON_RPC_CLIENT_TIMEOUT = 120.0

# ------------------------------------------------------------------------------

class JsonRpcClient:
    def __init__(
        self,
        address: str,
        port: int,
        ssl_context: Optional[ssl.SSLContext] = None,
        client_timeout: float = JSON_RPC_CLIENT_TIMEOUT,
        protocol: Optional[Protocol] = None
    ) -> None:
        super().__init__()
        self._tcp_client = TcpClient(address, port, ssl_context, client_timeout)
        self._protocol = protocol or XcpProtocol()
        self._seq = 0

    def __del__(self) -> None:
        self.disconnect()

    def __enter__(self) -> "JsonRpcClient":
        self._tcp_client.__enter__()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType]
    ) -> None:
        self._tcp_client.__exit__(exc_type, exc_value, traceback)

    @property
    def connected(self) -> bool:
        return self._tcp_client.connected

    def connect(self, timeout: float = JSON_RPC_DEFAULT_TIMEOUT) -> None:
        if self.connected:
            return

        self._tcp_client.connect(timeout)
        socket = self._tcp_client.socket
        assert socket

        self._seq += 1
        try:
            self._protocol.send_packet(
                socket.sock,
                self._protocol.create_packet(Protocol.MessageType.CONNECT, self._seq)
            )
        except Exception:
            self.disconnect()
            raise

    def disconnect(self) -> None:
        self._tcp_client.disconnect()

    def call(
        self,
        method: str,
        params: Union[JsonList, JsonDict, None] = None
    ) -> JsonValue:
        return self.call_with_timeout(JSON_RPC_DEFAULT_TIMEOUT, method, params)

    def call_with_timeout(
        self,
        timeout: float,
        method: str,
        params: Union[JsonList, JsonDict, None] = None
    ) -> JsonValue:
        remaining_time = timeout
        start_time = time.monotonic()

        while True:
            try:
                return self._call(remaining_time, method, params)
            except SocketDisconnectedError: # noqa: PERF203
                remaining_time = timeout - (time.monotonic() - start_time)
                if remaining_time <= 0:
                    raise

    def _call(
        self,
        connect_timeout: float,
        method: str,
        params: Union[JsonList, JsonDict, None]
    ) -> JsonValue:
        self.connect(connect_timeout)
        socket = self._tcp_client.socket
        assert socket
        sock = socket.sock

        self._seq += 1
        try:
            # 1. Send request.
            payload = JsonRpcRequest(self._seq, method, params).to_json().encode("utf-8")
            request = self._protocol.create_packet(Protocol.MessageType.REQUEST, self._seq, payload)
            if _DEBUG_CLIENT:
                log.debug(f"Send client request: {request} with payload: `{request.payload!r}`.")
            self._protocol.send_packet(sock, request)

            # 2. Receive response.
            response = self._protocol.receive_packet(sock, (Protocol.MessageType.RESPONSE, ))
            if _DEBUG_CLIENT:
                log.debug(f"Handle server response: {response} with payload: `{response.payload!r}`.")
            self._verify_sequence(response.seq)

            # 3. Return result.
            json_response = JsonRpcResponse.from_json(response.payload.decode("utf-8"))
            if not isinstance(json_response, JsonRpcResponse):
                raise ProtocolError(
                    f"Invalid JSON payload. Not a JsonRpcResponse. Got: `{type(json_response)}`."
                )

            if json_response.error is None:
                return json_response.result
            raise JsonRpcResponseError.from_payload(json_response.error)
        except (SocketDisconnectedError, KeyboardInterrupt):
            # Disconnect to prevent buffer corruption.
            self.disconnect()
            raise

    def _verify_sequence(self, seq: int) -> None:
        if self._seq != seq:
            raise ProtocolError(f"Invalid sequence detected. Current={seq}, expected={self._seq}.")
