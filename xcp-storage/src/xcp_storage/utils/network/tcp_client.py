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
from types import TracebackType

from xcp_storage.utils.network.socket import (
    create_client_sock,
    Socket,
    SocketDisconnectedError,
)
from xcp_storage.utils.sync import wait_for_condition

from xcp_storage.typing import (
    Optional,
    Type,
)

# ==============================================================================

class TcpClientError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)

# ------------------------------------------------------------------------------

class TcpClient:
    def __init__(
        self,
        address: str,
        port: int,
        ssl_context: Optional[ssl.SSLContext] = None,
        client_timeout: float = 120
    ) -> None:
        self._address = address
        self._port = port
        self._ssl_context = ssl_context
        self._client_timeout = client_timeout
        self._socket: Optional[Socket] = None

        self._entered_count = 0

    def __del__(self) -> None:
        self.disconnect()

    def __enter__(self) -> "TcpClient":
        if self._entered_count == 0:
            self.connect()
        self._entered_count += 1
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType]
    ) -> None:
        self._entered_count -= 1
        if self._entered_count == 0:
            self.disconnect()

    @property
    def socket(self) -> Optional[Socket]:
        return self._socket

    @property
    def connected(self) -> bool:
        return self._socket is not None

    def connect(self, timeout: float = 120) -> None:
        if self._socket:
            return

        error_message = ""
        def connect_impl() -> bool:
            nonlocal error_message
            try:
                self._socket = Socket(create_client_sock(
                    self._address,
                    self._port,
                    reuse_address=True,
                    keep_alive=True,
                    timeout=self._client_timeout,
                    ssl_context=self._ssl_context
                ))
            except Exception as e:
                error_message = str(e)
                return False
            return True

        if not wait_for_condition(connect_impl, timeout=timeout, interval=1):
            raise TcpClientError(f"Unable to connect to server: `{error_message}`.")

    def disconnect(self) -> None:
        if self._socket:
            self._socket.close()
        self._socket = None

    def send(self, buffer: bytes, size: Optional[int] = None) -> None:
        if self._socket:
            try:
                self._socket.send(buffer, size)
            except SocketDisconnectedError:
                self.disconnect()
                raise
        else:
            TcpClientError("Cannot send. Not connected.")

    def receive(self, buffer: bytearray, size: Optional[int] = None) -> None:
        if self._socket:
            try:
                self._socket.receive(buffer, size)
            except SocketDisconnectedError:
                self.disconnect()
                raise
        else:
            TcpClientError("Cannot receive. Not connected.")
