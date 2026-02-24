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

import asyncio
import ssl

import xcp_storage.log as log
from xcp_storage.utils.json import JsonDict
from xcp_storage.utils.json.rpc import (
    JsonRpcDispatcher,
    JsonRpcRequestProcessor,
    JsonRpcResponse,
    JsonRpcResponseParseError,
)
from xcp_storage.utils.network.protocol import Protocol, ProtocolError
from xcp_storage.utils.network.protocol.xcp import XcpProtocol
from xcp_storage.utils.network.tcp_server import TcpServer

from xcp_storage.typing import (
    Optional,
    override,
)

# ==============================================================================

class JsonRpcServer(TcpServer):
    def __init__(
        self,
        dispatcher: JsonRpcDispatcher,
        address: str,
        port: int,
        ssl_context: Optional[ssl.SSLContext] = None,
        protocol: Optional[Protocol] = None
    ) -> None:
        super().__init__(address, port, ssl_context)
        self._dispatcher = dispatcher
        self._protocol = protocol or XcpProtocol()

    @override
    async def _handle_client_connect(self, client: TcpServer.Client) -> bool:
        error_message = ""
        seq: Optional[int] = None
        try:
            _request = await self._protocol.receive_packet_async(client.reader, (Protocol.MessageType.CONNECT, ))
            return True
        except asyncio.IncompleteReadError:
            log.warning(f"Client connection of {client} has been closed before request processing!")
            return False
        except ProtocolError as e:
            error_message = str(e)
            seq = e.seq
        except Exception as e:
            error_message = str(e)

        log.error(f"Client error of {client} before request processing: `{error_message}`.")
        await self._send_parse_error(client, self.normalize_seq(seq), error_message)
        return False

    @override
    async def _handle_client_disconnect(self, client: TcpServer.Client) -> None:
        pass

    @override
    async def _handle_client_request(self, client: TcpServer.Client) -> bool:
        error_message = ""
        seq: Optional[int] = None
        payload = None
        try:
            # 1. Get request.
            request = await self._protocol.receive_packet_async(client.reader, (Protocol.MessageType.REQUEST, ))
            seq = request.seq

            # 2. Execute request.
            payload = await asyncio.get_running_loop().run_in_executor(
                None,
                self._process_packet_request,
                self._dispatcher,
                request
            )
        except asyncio.IncompleteReadError:
            log.warning(f"Client connection of {client} has been closed during request processing!")
            return False
        except ProtocolError as e:
            error_message = str(e)
            seq = e.seq
        except Exception as e:
            error_message = str(e)

        # 3. Send response.
        seq = self.normalize_seq(seq)
        if payload is not None:
            response = self._protocol.create_packet(Protocol.MessageType.RESPONSE, seq, payload)
            await self._protocol.send_packet_async(client.writer, response)
        else:
            log.error(f"Client error of {client} during request processing: `{error_message}`.")
            await self._send_parse_error(client, seq, error_message)

        return True

    async def _send_parse_error(self, client: TcpServer.Client, seq: int, message: str) -> None:
        data: JsonDict = {"message": message}
        payload = JsonRpcResponse(error=JsonRpcResponseParseError(data=data).payload).to_json().encode("utf-8")
        response = self._protocol.create_packet(Protocol.MessageType.RESPONSE, seq, payload)
        await self._protocol.send_packet_async(client.writer, response)

    @staticmethod
    def normalize_seq(seq: Optional[int]) -> int:
        return seq if seq is not None else -1

    @staticmethod
    def _process_packet_request(dispatcher: JsonRpcDispatcher, packet: Protocol.Packet) -> bytes:
        response = JsonRpcRequestProcessor(dispatcher).process(
            packet.payload.decode("utf-8")
        )
        if response:
            return response.to_json().encode("utf-8")
        return b""
