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

from abc import ABC, abstractmethod
import asyncio
import ssl

import xcp_storage.log as log
from xcp_storage.utils.asyncio import cancel_event_loop_tasks, close_stream_writer
from xcp_storage.utils.network.socket import create_server_sock, Socket

from xcp_storage.typing import (
    Any,
    Optional,
    override,
    Set,
)

# ==============================================================================

class TcpServerError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)

# ------------------------------------------------------------------------------

class TcpServer(ABC):
    class Client:
        def __init__(
            self,
            peername: Any, # noqa: ANN401
            reader: asyncio.StreamReader,
            writer: asyncio.StreamWriter
        ) -> None:
            self.peername: Any = peername
            self.reader = reader
            self.writer = writer

        @override
        def __str__(self) -> str:
            return str(self.peername)

    def __init__(
        self,
        hostname: str,
        port: int,
        ssl_context: Optional[ssl.SSLContext] = None
    ) -> None:
        self._hostname = hostname
        self._port = port
        self._ssl_context = ssl_context

        self._running = False

        self._event_loop: Optional[asyncio.AbstractEventLoop] = None

        self._server_socket: Optional[Socket] = None
        self._server: Optional[asyncio.AbstractServer] = None

        self._clients: Set[TcpServer.Client] = set()

    def run(self) -> None:
        if self._running:
            raise TcpServerError("Server is already running.")

        self._running = True

        try:
            log.info(f"Running TCP server on `{self._hostname}:{self._port}`...")
            self._server_socket = Socket(create_server_sock(
                self._hostname,
                self._port,
                reuse_address=True,
                keep_alive=True,
                timeout=0.0, # 0 here to set non-blocking mode.
                ssl_context=self._ssl_context
            ))

            old_event_loop = asyncio.get_event_loop()
            self._event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._event_loop)

            self._server = self._event_loop.run_until_complete(asyncio.start_server(
                self._handle_client,
                sock=self._server_socket.sock,
                loop=self._event_loop
            ))

            log.info("TCP server started!")
            self._event_loop.run_forever()
        except KeyboardInterrupt:
            log.info("Closing server because break signal has been received...")
        finally:
            if self._event_loop:
                if self._server:
                    self._server.close()
                    self._event_loop.run_until_complete(self._server.wait_closed())
                    self._server = None

                try:
                    cancel_event_loop_tasks(self._event_loop)
                finally:
                    self._event_loop.close()
                    self._event_loop = None
                    asyncio.set_event_loop(old_event_loop)

            if self._server_socket:
                self._server_socket.close()
                self._server_socket = None

            self._clients.clear()
            self._running = False

    async def _handle_client( # noqa: C901
        self,
        client_reader: asyncio.StreamReader,
        client_writer: asyncio.StreamWriter
    ) -> None:
        client = self.Client(client_writer.get_extra_info("peername"), client_reader, client_writer)
        log.info(f"New client {client} connected.")
        self._clients.add(client)

        rejected = False
        try:
            if not await self._handle_client_connect(client):
                rejected = True
                return
            while not client_writer.is_closing():
                await self._handle_client_request(client)
            log.info(f"Client {client} has terminated.")
        except asyncio.TimeoutError as e:
            log.error(f"Timeout reached for client {client}: `{e}`.")
        except Exception as e:
            log.error(f"Unhandled exception for client {client}: `{e}`.")
        finally:
            if not rejected:
                try:
                    await self._handle_client_disconnect(client)
                except Exception as e:
                    log.error(f"Unhandled exception for client {client} during disconnect: `{e}`.")

            await close_stream_writer(client_writer)
            log.info(f"Client {client} disconnected.")
            self._clients.remove(client)

    @abstractmethod
    async def _handle_client_connect(self, client: Client) -> bool:
        return False

    @abstractmethod
    async def _handle_client_disconnect(self, client: Client) -> None:
        pass

    @abstractmethod
    async def _handle_client_request(self, client: Client) -> None:
        pass
