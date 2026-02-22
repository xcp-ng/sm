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
from enum import IntEnum

from xcp_storage.typing import Optional, Sequence

# ==============================================================================

class ProtocolError(Exception):
    def __init__(self, message: str, seq: Optional[int] = None) -> None:
        super().__init__(message)
        self.seq = seq

# ------------------------------------------------------------------------------

class Protocol(ABC):
    class MessageType(IntEnum):
        CONNECT = 0
        REQUEST = 1
        RESPONSE = 2

    class Packet(ABC):
        @abstractmethod
        def encode(self) -> bytes:
            pass

        @property
        @abstractmethod
        def message_type(self) -> "Protocol.MessageType":
            pass

        @property
        @abstractmethod
        def seq(self) -> int:
            pass

        @property
        @abstractmethod
        def payload(self) -> bytes:
            pass

    @abstractmethod
    def create_packet(self, message_type: MessageType, seq: int, payload: Optional[bytes]) -> Packet:
        pass

    @abstractmethod
    async def receive_packet_async(
        self,
        stream_reader: asyncio.StreamReader,
        message_types: Sequence[MessageType]
    ) -> Packet:
        pass

    @abstractmethod
    async def send_packet_async(
        self,
        stream_writer: asyncio.StreamWriter,
        packet: Packet
    ) -> None:
        pass
