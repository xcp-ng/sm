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

import util

# ==============================================================================

class BackupManager(ABC):
    def __init__(self, *, files_to_keep, enabled=True, remove_expired_on_backup=True):
        self._files_to_keep = files_to_keep
        self._enabled = enabled
        self._remove_expired_on_backup = remove_expired_on_backup

    def _type(self):
        return type(self).__name__

    # ----------------------------------
    # Backup file naming.
    # ----------------------------------

    @abstractmethod
    def _backup_dir_path(self, ctx):
        pass

    @abstractmethod
    def _format_backup_file_name(self, ctx, counter):
        pass

    def _next_backup_file_path(self, ctx):
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
    def _backup_files(self, ctx):
        pass

    def _sorted_backup_files(self, ctx, *, reverse=False):
        return sorted(self._backup_files(ctx),
                      reverse=reverse,
                      key=lambda p: p[1])

    def _latest_backup_file(self, ctx):
        return max(self._backup_files(ctx),
                   default=(None, datetime.fromtimestamp(0)),
                   key=lambda p: p[1])

    def backup_age(self, ctx):
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

    def _check_file_for_retention(self, _file_path):
        return self.FileRetentionCheckResult.CHECK

    def remove_expired(self, ctx):
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
                    f"Unable to unlink backup file of type `{self._type()}` at `{file_path}`: {e}"
                )

    # ----------------------------------
    # Backup ops.
    # ----------------------------------

    @abstractmethod
    def _do_backup(self, ctx):
        pass

    def try_backup(self, ctx):
        if not self._enabled:
            return False

        try:
            backup_file_path = self._do_backup(ctx)

            if self._remove_expired_on_backup:
                self.remove_expired(ctx)
        except Exception as e:
            util.SMlog(f"Failed to create backup ({self._type()} with context `{ctx}`): {e}")
            return False

        util.SMlog(f"Backup of type {self._type()} created in `{backup_file_path}`")
        return True
