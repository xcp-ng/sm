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

import itertools
from abc import ABC, abstractmethod
from datetime import datetime
from enum import IntEnum
from pathlib import Path

import util

from sm_typing import Generator, Generic, List, Optional, Tuple, TypeVar, Union

T = TypeVar("T")

BackupItem = Tuple[Path, datetime]

# ==============================================================================

class BackupManager(ABC, Generic[T]):
    def __init__(
        self,
        *,
        files_to_keep: int,
        enabled: bool = True,
        remove_expired_on_backup: bool = True
    ) -> None:
        self._files_to_keep = files_to_keep
        self._enabled = enabled
        self._remove_expired_on_backup = remove_expired_on_backup

    @property
    def _type_name(self) -> str:
        return type(self).__name__

    # ----------------------------------
    # Backup file naming.
    # ----------------------------------

    @abstractmethod
    def _backup_dir_path(self, ctx: T) -> Path:
        """
        Get the path to the directory where to create backups.

        :param ctx: Implementation-specific context.
        :return: The path to the backup directory.
        """

    @abstractmethod
    def _format_backup_file_name(self, ctx: T, counter: Optional[int]) -> str:
        """
        Format the name of a new backup file.

        :param ctx: Implementation-specific context.
        :param counter: Optional counter to distinguish between
        identically-named backup files.
        :return: The name of the new backup file.
        """

    def _next_backup_file_path(self, ctx: T) -> Path:
        """
        Get the path to a new backup file.

        :param ctx: Implementation-specific context.
        :return: The path to the new backup file.
        """
        dst_dir = self._backup_dir_path(ctx)
        file_path = dst_dir / self._format_backup_file_name(ctx, None)
        counter = 1

        while file_path.exists():
            file_path = dst_dir / self._format_backup_file_name(ctx, counter)
            counter += 1

        return file_path

    # ----------------------------------
    # Backup file listing.
    # ----------------------------------

    @abstractmethod
    def _backup_files(self, ctx: T) -> Generator[BackupItem, None, None]:
        """
        Get a generator to the visible backup files in the backup directory.

        Each backup item is a tuple of the backup file path and its creation
        date.

        :param ctx: Implementation-specific context.
        :return: The generator to the backup file items.
        """

    def _sorted_backup_files(
        self,
        ctx: T,
        *,
        reverse: bool = False
    ) -> List[BackupItem]:
        """
        Get a list of backup files sorted by creation date.

        :param ctx: Implementation-specific context.
        :param reverse: Whether to reverse sorting.
        :return: The list of sorted backup file items.
        """
        return sorted(self._backup_files(ctx),
                      reverse=reverse,
                      key=lambda p: p[1])

    def _latest_backup_file(self, ctx: T) -> Union[BackupItem, Tuple[None, datetime]]:
        """
        Get the latest backup file, and its creation date.

        Returns (None, timestamp(0)) when none are found.

        :param ctx: Implementation-specific context.
        :return: The latest backup file item.
        """
        return max(self._backup_files(ctx),
                   default=(None, datetime.fromtimestamp(0)),
                   key=lambda p: p[1])

    def backup_age(self, ctx: T) -> float:
        """
        Get the latest backup age in seconds.

        :param ctx: Implementation-specific context.
        :return: The latest backup age in seconds.
        """
        return (datetime.now() - self._latest_backup_file(ctx)[1]).total_seconds()

    # ----------------------------------
    # Retention ops.
    # ----------------------------------

    class FileRetentionCheckResult(IntEnum):
        # Perform the common checks on the file.
        CHECK = 0
        # Forcefully retain the file.
        RETAIN = 1
        # Forcefully remove the file.
        REMOVE = 2

    def _check_file_for_retention(self, _file_path: Path) -> FileRetentionCheckResult:
        """
        Check a backup file for a custom per-file retention policy.

        :param _file_path: Path to the backup file to check.
        :return: The result of the check.
        """
        return self.FileRetentionCheckResult.CHECK

    def remove_expired(self, ctx: T) -> None:
        """
        Remove backup files considered expired based on the retention policy.

        :param ctx: Implementation-specific context.
        """
        backup_files = self._sorted_backup_files(ctx)
        older_files = backup_files[:-self._files_to_keep]
        newer_files = backup_files[-self._files_to_keep:]

        # These files are to be removed by default, unless forcefully retained.
        older_files = [
            file for file in older_files
            if self._check_file_for_retention(file[0]) != self.FileRetentionCheckResult.RETAIN
        ]

        # These files are to be retained by default, unless forcefully removed.
        newer_files = [
            file for file in newer_files
            if self._check_file_for_retention(file[0]) == self.FileRetentionCheckResult.REMOVE
        ]

        # If there are forcefully removed files, we need to keep some of the
        # older files to reach the requested amount of files to keep.
        if newer_files:
            older_files = older_files[:-len(newer_files)]

        for file_path, _ in itertools.chain(older_files, newer_files):
            try:
                file_path.unlink()
            except OSError as e:
                util.SMlog(
                    f"Unable to unlink backup file of type `{self._type_name}` at `{file_path}`: {e}",
                    priority=util.LOG_ERR
                )

    # ----------------------------------
    # Backup ops.
    # ----------------------------------

    @abstractmethod
    def _do_backup(self, ctx: T) -> Path:
        """
        Create a backup.

        :param ctx: Implementation-specific context.
        :return: The path to the new backup file.
        """

    def try_backup(self, ctx: T) -> bool:
        """
        Tries to create a backup.

        This is a best-effort operation: if it fails, no exception is raised and
        it is up to the caller to react according to the return value.

        This also removes expired backup files if the retention policy allows it.

        :param ctx: Implementation-specific context.
        :return: True if a new backup was created, False otherwise.
        """
        if not self._enabled:
            return False

        try:
            backup_file_path = self._do_backup(ctx)

            if self._remove_expired_on_backup:
                self.remove_expired(ctx)
        except Exception as e:
            util.SMlog(
                f"Failed to create backup ({self._type_name} with context `{ctx}`): {e}",
                priority=util.LOG_ERR
            )

            return False

        util.SMlog(f"Backup of type {self._type_name} created in `{backup_file_path}`")
        return True
