#!/usr/bin/python3
#
# Copyright (C) 2020  Vates SAS - antoine.bartuccio@vates.fr
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
import util
from sm_typing import Dict, override, Tuple, Collection, Any, TypeVar, Type
import xs_errors

import abc

LogEntry = TypeVar("LogEntry", bound="BaseLogEntry")


class BaseLogEntry(abc.ABC):
    """Base class for serializing journal based entries intended to rollback failed operations"""

    @property  # type: ignore # Only way to simulate an abstract class variable
    @classmethod
    @abc.abstractmethod
    def CURRENT_VERSION(cls) -> str: ...

    @property  # type: ignore # Only way to simulate an abstract class variable
    @classmethod
    @abc.abstractmethod
    def JRN_KEY(cls) -> str: ...

    @classmethod
    @abc.abstractmethod
    def from_dict(cls: Type[LogEntry], data: Dict[str, Any]) -> LogEntry: ...

    @abc.abstractmethod
    def to_dict(self) -> Dict[str, Collection[Any]]: ...

    @staticmethod
    def _get_version_from_journal_id(journal_id: str) -> str:
        _, version = journal_id.split("+")
        return version.replace("-", ".")

    @classmethod
    def from_journal(cls: Type[LogEntry], journal_id: str, value: str) -> LogEntry:
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
