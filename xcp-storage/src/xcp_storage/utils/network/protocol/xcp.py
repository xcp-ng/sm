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
from enum import IntFlag
import socket
import struct

from xcp_storage.utils.network.protocol import Protocol, ProtocolError
from xcp_storage.utils.network.socket import socket_receive, socket_send

from xcp_storage.typing import (
    Never,
    Optional,
    override,
    Sequence,
)

# ==============================================================================

class XcpProtocol(Protocol):
    # 16 bytes:
    # 0x00  4s   4   Magic: `@XCP`.
    # 0x04   H   2   Protocol version.
    # 0x06   B   1   Message type.
    # 0x07   H   2   Message flags.
    # 0x09   H   2   Sequence number.
    # 0x0B   I   4   Payload size.
    # 0x0F   H   1   Reserved.

    HEADER_FORMAT = "!4sHBHHIH"
    HEADER_MAGIC = b"@XCP"
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
    VERSION = 1

    MAX_PACKET_SIZE = 32 << 20 # 32 MiB

    class MessageFlags(IntFlag):
        NONE = 0

    class Packet(Protocol.Packet):
        def __init__(
            self,
            message_type: Protocol.MessageType,
            message_flags: "XcpProtocol.MessageFlags",
            seq: int,
            payload: Optional[bytes]
        ) -> None:
            self._payload = payload or b""

            # Header data.
            self._message_type = message_type
            self._message_flags = message_flags
            self._seq = seq
            self._payload_size = len(self._payload)

            self.total_size = XcpProtocol.HEADER_SIZE + self._payload_size
            if self.total_size > XcpProtocol.MAX_PACKET_SIZE:
                self._raise_too_large_packet(self.total_size, self._seq)

        @override
        def encode(self) -> bytes:
            return struct.pack(
                XcpProtocol.HEADER_FORMAT,
                XcpProtocol.HEADER_MAGIC,
                XcpProtocol.VERSION,
                self._message_type,
                self._message_flags,
                self._seq,
                self._payload_size,
                0
            ) + self._payload

        @property
        @override
        def message_type(self) -> Protocol.MessageType:
            return self._message_type

        @property
        @override
        def seq(self) -> int:
            return self._seq

        @property
        @override
        def payload(self) -> bytes:
            return self._payload

        @property
        def payload_size(self) -> int:
            return self._payload_size

        def set_payload(self, payload: bytes) -> None:
            if len(payload) != self._payload_size:
                raise ProtocolError("Incompatible payload size.", self._seq)

        @classmethod
        def from_header(cls, header: bytes) -> "XcpProtocol.Packet":
            header_magic, \
            protocol_version, \
            message_type, \
            message_flags, \
            seq, \
            payload_size, _ = struct.unpack(XcpProtocol.HEADER_FORMAT, header)

            if header_magic != XcpProtocol.HEADER_MAGIC:
               raise ProtocolError("Invalid magic value!", seq)
            if protocol_version != XcpProtocol.VERSION:
                raise ProtocolError(
                    f"Invalid protocol version! Packet={protocol_version}. Expected={XcpProtocol.VERSION}.",
                    seq
                )

            total_size = XcpProtocol.HEADER_SIZE + payload_size
            if total_size > XcpProtocol.MAX_PACKET_SIZE:
                cls._raise_too_large_packet(total_size, seq)

            packet = cls(message_type, message_flags, seq, None)
            packet.total_size = total_size
            return packet

        @staticmethod
        def _raise_too_large_packet(total_size: int, seq: int) -> Never:
            raise ProtocolError(f"Packet is too large! {total_size} > {XcpProtocol.MAX_PACKET_SIZE}.", seq)

    @override
    def create_packet(
        self, message_type: Protocol.MessageType, seq: int, payload: Optional[bytes] = None
    ) -> Protocol.Packet:
        return self.Packet(
            message_type,
            self.MessageFlags.NONE,
            seq,
            payload
        )

    @override
    def receive_packet(self, sock: socket.socket, message_types: Sequence[Protocol.MessageType]) -> Protocol.Packet:
        if self.MessageType.CONNECT in message_types:
            return self.Packet(self.MessageType.CONNECT, self.MessageFlags.NONE, -1, None)

        self._assert_supported_message_types(message_types)

        header = bytearray(self.HEADER_SIZE)
        socket_receive(sock, header)
        packet = self.Packet.from_header(header)

        self._assert_request_packet(packet)
        payload = bytearray(packet.payload_size)
        socket_receive(sock, payload)
        packet.set_payload(payload)

        return packet

    @override
    def send_packet(self, sock: socket.socket, packet: Protocol.Packet) -> None:
        if packet.message_type != self.MessageType.CONNECT: # We don't use CONNECT feature in this protocol.
            socket_send(sock, packet.encode())

    @override
    async def receive_packet_async(
        self,
        stream_reader: asyncio.StreamReader,
        message_types: Sequence[Protocol.MessageType]
    ) -> Packet:
        if self.MessageType.CONNECT in message_types:
            return self.Packet(self.MessageType.CONNECT, self.MessageFlags.NONE, -1, None)

        self._assert_supported_message_types(message_types)

        header = await stream_reader.readexactly(self.HEADER_SIZE)
        packet = self.Packet.from_header(header)

        self._assert_request_packet(packet)
        payload = await stream_reader.readexactly(packet.payload_size)
        packet.set_payload(payload)

        return packet

    @override
    async def send_packet_async(
        self,
        stream_writer: asyncio.StreamWriter,
        packet: Protocol.Packet
    ) -> None:
        if packet.message_type != self.MessageType.CONNECT:
            stream_writer.write(packet.encode())
            await stream_writer.drain()

    @classmethod
    def _assert_request_packet(cls, packet: Protocol.Packet) -> None:
        if packet.message_type != cls.MessageType.REQUEST:
            raise ProtocolError(f"Unexpected message type: {packet.message_type}. Expected: REQUEST.", packet.seq)

    @classmethod
    def _assert_supported_message_types(cls, message_types: Sequence[Protocol.MessageType]) -> None:
        if cls.MessageType.REQUEST not in message_types:
            raise ProtocolError("Only CONNECT and REQUEST are supported by XCP protocol.")
