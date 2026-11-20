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

import shutil
import time
from datetime import datetime
from pathlib import Path

import util
from backupmanager import BackupItem, BackupManager

from sm_typing import Final, Generator, Optional, override

# ==============================================================================

# Global parameters for LVM metadata backups.
ENABLED: Final = True
FILES_TO_KEEP: Final = 30

BACKUP_FILE_NAME_DATE_FORMAT: Final = "%Y%m%d_%H%M%S"

# Paths to the directories where the files to backup are (managed by LVM),
# and where to copy them (managed by the SM).
SRC_PATH: Final = Path("/etc/lvm/backup")
DST_PATH: Final = Path("/etc/sm/lvm-backups")

# ------------------------------------------------------------------------------

class LVMMetadataBackup(BackupManager[str]):
    def __init__(self) -> None:
        super().__init__(files_to_keep=FILES_TO_KEEP, enabled=ENABLED)

    # ----------------------------------
    # Backup file naming.
    # ----------------------------------

    @override
    def _backup_dir_path(self, ctx: str) -> Path:
        return DST_PATH / ctx

    @override
    def _format_backup_file_name(self, _ctx: str, counter: Optional[int]) -> str:
        formatted_time = time.strftime(BACKUP_FILE_NAME_DATE_FORMAT)

        if counter is not None:
            return f"{formatted_time}.{counter}.vg"

        return f"{formatted_time}.vg"

    # ----------------------------------
    # Backup file listing.
    # ----------------------------------

    @override
    def _backup_files(self, ctx: str) -> Generator[BackupItem, None, None]:
        backup_dir_path = self._backup_dir_path(ctx)

        try:
            for file_path in backup_dir_path.iterdir():
                try:
                    yield file_path, datetime.fromtimestamp(file_path.stat().st_mtime)
                except OSError as e:
                    util.SMlog(
                        f"Unable to stat LVM metadata backup file `{file_path}`: {e}",
                        priority=util.LOG_ERR
                    )

                    continue
        except OSError as e:
            util.SMlog(
                f"Unable to get files of LVM metadata backup directory `{backup_dir_path}`: {e}",
                priority=util.LOG_ERR
            )

    # ----------------------------------
    # Backup ops.
    # ----------------------------------

    @override
    def _do_backup(self, ctx: str) -> Path:
        dst_dir = self._backup_dir_path(ctx)
        dst_dir.mkdir(parents=True, exist_ok=True)

        source_file_path = SRC_PATH / ctx
        backup_file_path = self._next_backup_file_path(ctx)

        shutil.copyfile(source_file_path, backup_file_path)
        return backup_file_path

    def remove_vg_backups(self, vgname: str) -> None:
        """
        Remove the metadata backup files of a LVM volume group.

        This is a best-effort operation: if it fails, no exception is raised.

        :param str vgname: The name of the volume group to remove the backup files of.
        """
        try:
            shutil.rmtree(self._backup_dir_path(vgname))
        except Exception as e:
            util.SMlog(
                f"Failed to remove LVM metadata backups of `{vgname}`: {e}",
                priority=util.LOG_ERR
            )
