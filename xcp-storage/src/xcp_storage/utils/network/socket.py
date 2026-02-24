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
import errno
import ipaddress
import select
import socket
import ssl
from types import TracebackType

from xcp_storage.typing import (
    Any,
    Dict,
    Optional,
    Tuple,
    Type,
    Union,
)

# ==============================================================================

_FAMILY_TO_STR = {
    socket.AF_INET: "IPv4",
    socket.AF_INET6: "IPv6",
    socket.AF_UNIX: "Unix"
}

_IP_VERSION_TO_FAMILY = {
    4: socket.AF_INET,
    6: socket.AF_INET6,
    0: socket.AF_UNSPEC
}

_SERVER_BACKLOG = 128

# ------------------------------------------------------------------------------

class SocketError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)

class SocketTimeoutError(SocketError):
    def __init__(self) -> None:
        super().__init__("Socket timeout.")

class SocketDisconnectedError(SocketError):
    def __init__(self, message: str) -> None:
        super().__init__(message)

# ------------------------------------------------------------------------------

def get_ip_address(address: str, ip_version: int = 0) -> Union[ipaddress.IPv4Address, ipaddress.IPv6Address]:
    # Note: `address` can be a hostname or IP.
    with contextlib.suppress(ValueError):
        return ipaddress.ip_address(address)

    family = _IP_VERSION_TO_FAMILY.get(ip_version)
    if family is None:
        raise SocketError("Unknown IP version.")

    try:
        info = socket.getaddrinfo(address or socket.gethostname(), 80, family, socket.SOCK_STREAM, socket.SOL_TCP)
        return ipaddress.ip_address(info[0][4][0])
    except socket.gaierror as e:
        raise SocketError(f"Cannot resolve IP: `{e}`.") from None
    except IndexError:
        raise SocketError("Cannot resolve IP.") from None

# ------------------------------------------------------------------------------

def format_address(address: str, port: int) -> Tuple[socket.AddressFamily, Union[
    Tuple[str, int],
    Tuple[str, int, int, int]
]]:
    if not address:
        raise SocketError("No hostname/IP.")

    ip_address = get_ip_address(address)
    if ip_address.version == 4:
        family = socket.AF_INET
        return (family, (str(ip_address), port))
    elif ip_address.version == 6:
        family = socket.AF_INET6
        return (family, (str(ip_address), port, 0, 0))

    raise SocketError("Unknown IP version.")

# ------------------------------------------------------------------------------

def _create_stream_sock(
    address: str,
    family: socket.AddressFamily,
    *,
    bind: bool,
    reuse_address: bool,
    ssl_context: Optional[ssl.SSLContext]
) -> socket.socket:
    sock = socket.socket(family, socket.SOCK_STREAM)
    if ssl_context:
        if bind:
            sock = ssl_context.wrap_socket(sock, server_side=True)
        else:
            sock = ssl_context.wrap_socket(sock, server_side=False, server_hostname=address or None)

    if reuse_address:
        set_socket_reuseaddr(sock)

    return sock

def _normalize_timeout(timeout: Optional[float]) -> Optional[float]:
    if timeout is not None and timeout < 0:
        timeout = None
    return timeout

# ------------------------------------------------------------------------------

def create_server_sock(
    address: str,
    port: int,
    *,
    reuse_address: bool = True,
    keep_alive: bool = True,
    timeout: Optional[float] = None,
    ssl_context: Optional[ssl.SSLContext] = None
) -> socket.socket:
    family, bind = format_address(address, port)
    sock = _create_stream_sock(address, family, bind=True, reuse_address=reuse_address, ssl_context=ssl_context)

    timeout = _normalize_timeout(timeout)
    if timeout:
        sock.settimeout(timeout)

    try:
        sock.bind(bind)
        sock.listen(_SERVER_BACKLOG)
    except OSError as e:
        with contextlib.suppress(Exception):
            sock.close()
        raise SocketError(f"Failed to bind server sock: `{e}`.") from None

    if keep_alive:
        set_socket_keepalive(sock)

    return sock

def create_client_sock(
    address: str,
    port: int,
    *,
    reuse_address: bool = True,
    keep_alive: bool = True,
    timeout: Optional[float] = None,
    ssl_context: Optional[ssl.SSLContext] = None
) -> socket.socket:
    family, connect = format_address(address, port)
    sock = _create_stream_sock(address, family, bind=False, reuse_address=reuse_address, ssl_context=ssl_context)

    timeout = _normalize_timeout(timeout)
    if timeout:
        sock.settimeout(timeout)

    while True:
        try:
            sock.connect(connect)
            break
        except OSError as e:
            if e.errno in (errno.EAGAIN, errno.EINPROGRESS):
                _, ready, _ = select.select([], [sock], [], timeout)
                if sock in ready:
                    continue

            with contextlib.suppress(Exception):
                sock.close()
            raise

    if keep_alive:
        set_socket_keepalive(sock)

    return sock

# ------------------------------------------------------------------------------

def set_socket_reuseaddr(sock: socket.socket) -> None:
    with contextlib.suppress(Exception):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

def set_socket_keepalive(sock: socket.socket) -> None:
    with contextlib.suppress(Exception):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

# ------------------------------------------------------------------------------

def _get_buffer_size(buffer: Union[bytes, bytearray], size: Optional[int] = None) -> int:
    if size is None:
        size = len(buffer)
    else:
        assert len(buffer) >= size, "Buffer size must be greater than or equal to size."
    return size

# ------------------------------------------------------------------------------

def socket_send(sock: socket.socket, buffer: bytes, size: Optional[int] = None) -> None:
    size = _get_buffer_size(buffer, size)
    view = memoryview(buffer)

    pos = 0
    while pos < size:
        try:
            n = sock.send(view[pos:size])
            if not n:
                break
            pos += n
        except TimeoutError:
            raise SocketTimeoutError() from None
        except OSError as e:
            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                select.select([], [sock], [])
                continue
            raise SocketDisconnectedError(f"Unable to send data: `{e}`.") from None

    if pos != size:
        raise SocketDisconnectedError("Not enough data sent.") from None

# ------------------------------------------------------------------------------

def socket_receive(sock: socket.socket, buffer: bytearray, size: Optional[int] = None) -> None:
    size = _get_buffer_size(buffer, size)
    view = memoryview(buffer)

    pos = 0
    while pos < size:
        try:
            n = sock.recv_into(view[pos:], min(size - pos, 8192))
            if not n:
                break
            pos += n
        except TimeoutError:
            raise SocketTimeoutError() from None
        except OSError as e:
            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                select.select([sock], [], [])
                continue
            raise SocketDisconnectedError(f"Unable to receive data: `{e}`.") from None

    if pos != size:
        raise SocketDisconnectedError("Not enough data received.") from None

# ------------------------------------------------------------------------------

def get_socket_family_str(sock: socket.socket) -> str:
    return _FAMILY_TO_STR.get(sock.family, "Unknown")

# ------------------------------------------------------------------------------

class Socket:
    def __init__(self, sock: socket.socket, keep_open: bool = False) -> None:
        self.sock = sock
        self.keep_open = keep_open

    def __del__(self) -> None:
        self.close()

    def __enter__(self) -> "Socket":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType]
    ) -> None:
        self.close()

    def send(self, buffer: bytes, size: Optional[int] = None) -> None:
        socket_send(self.sock, buffer, size)

    def receive(self, buffer: bytearray, size: Optional[int] = None) -> None:
        socket_receive(self.sock, buffer, size)

    def close(self) -> None:
        if self.keep_open:
            return
        with contextlib.suppress(Exception):
            self.sock.shutdown(socket.SHUT_RDWR)
        with contextlib.suppress(Exception):
            self.sock.close()

    @property
    def family_str(self) -> str:
        return get_socket_family_str(self.sock)

    @property
    def timeout(self) -> Optional[float]:
        return self.sock.gettimeout()

    @timeout.setter
    def timeout(self, value: Optional[float]) -> None:
        self.sock.settimeout(value)

    @property
    def peer_certificate(self) -> Optional[Dict[str, Any]]:
        if isinstance(self.sock, ssl.SSLSocket):
            return self.sock.getpeercert()
        return None
