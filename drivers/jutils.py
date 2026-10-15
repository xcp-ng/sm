#!/usr/bin/python3
#
# Copyright (C) 2026  Vates SAS - antoine.bartuccio@vates.tech
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
#
# Utilities for journal based operations

import json
from abc import ABC, abstractmethod

import util
import xs_errors

from sm_typing import Any, ClassVar, Collection, Dict, Tuple, Type, TypeVar, override

LogEntry = TypeVar("LogEntry", bound="BaseLogEntry")


class BaseLogEntry(ABC):
    """Base class for serializing journal based entries intended to rollback failed operations"""

    CURRENT_VERSION: ClassVar[str]

    JRN_KEY: ClassVar[str]

    @classmethod
    @abstractmethod
    def from_dict(cls: Type[LogEntry], data: Dict[str, Any]) -> LogEntry: ...

    @abstractmethod
    def to_dict(self) -> Dict[str, Collection[Any]]: ...

    @staticmethod
    def _get_version_from_journal_id(journal_id: str) -> str:
        _, version = journal_id.split("+")
        return version.replace("-", ".")

    @classmethod
    def from_journal(cls: Type[LogEntry], journal_id: str, value: str) -> LogEntry:
        """Convert a compatilbe journal to a log entry
        Ensure that the type and version of the journal are compatible"""
        version = cls._get_version_from_journal_id(journal_id)
        if version != cls.CURRENT_VERSION:
            raise xs_errors.SRException(
                f"Could not revert operation {journal_id} with mismatched log versions {version} != {cls.CURRENT_VERSION}"
            )
        return cls.from_dict(json.loads(value))

    def to_journal(self) -> Tuple[str, str]:
        # We use + as a version delimiter to not clash with journaler file name parsing
        journal_id = f"{util.gen_uuid()}+{self.CURRENT_VERSION.replace('.', '-')}"
        value = json.dumps(self.to_dict())
        return journal_id, value

    @override
    def __str__(self) -> str:
        return str(self.to_dict())
