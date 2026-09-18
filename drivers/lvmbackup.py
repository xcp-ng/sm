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
from pathlib import Path

import util

# Global parameters for LVM metadata backups.
ENABLED = True
FILES_TO_KEEP = 30

BACKUP_FILE_NAME_DATE_FORMAT = "%Y%m%d_%H%M%S"

# Paths to the directories where the files to backup are (managed by LVM),
# and where to copy them (managed by the SM).
SRC_PATH = Path("/etc/lvm/backup")
DST_PATH = Path("/etc/lvm/sm-backups")

# ==============================================================================

def _vg_backup_dir_path(vgname):
    return DST_PATH / vgname


def _next_backup_file_path(dst_dir):
    formatted_time = time.strftime(BACKUP_FILE_NAME_DATE_FORMAT)
    file_path = dst_dir / f"{formatted_time}.vg"
    i = 1

    while file_path.exists():
        file_path = dst_dir / f"{formatted_time}.{i}.vg"
        i += 1

    return file_path


# ==============================================================================

def _do_backup(vgname):
    dst_dir = _vg_backup_dir_path(vgname)
    dst_dir.mkdir(parents=True, exist_ok=True)

    source_file_path = SRC_PATH / vgname
    backup_file_path = _next_backup_file_path(dst_dir)

    shutil.copyfile(source_file_path, backup_file_path)
    return backup_file_path


def _remove_expired(vgname):
    dest_dir = _vg_backup_dir_path(vgname)
    existing_files = []

    try:
        for file_path in dest_dir.iterdir():
            try:
                existing_files.append((file_path.stat().st_mtime, file_path))
            except OSError as e:
                util.SMlog(
                    f"Unable to stat LVM metadata backup file `{file_path}`: {e}"
                )

                continue
    except OSError as e:
        util.SMlog(
            f"Unable to get files of LVM metadata backup directory `{dest_dir}`: {e}"
        )

        return

    existing_files.sort()
    oldest_files = existing_files[:-FILES_TO_KEEP]

    for _, file_path in oldest_files:
        try:
            file_path.unlink()
        except OSError as e:
            util.SMlog(
                f"Unable to unlink LVM metadata backup file `{file_path}`: {e}"
            )


# ==============================================================================

def backup_vg(vgname):
    """
    Back up the metadata of a LVM volume group to a SM-managed directory.

    This is a best-effort operation: if it fails, no exception is raised and
    it is up to the caller to react according to the return value.

    :param vgname: The name of the volume group to back up.
    :return: True if a new backup was created, False otherwise.
    """
    if not ENABLED:
        return False

    try:
        backup_file_path = _do_backup(vgname)
        _remove_expired(vgname)
    except Exception as e:
        util.SMlog(f"Failed to back up LVM metadata of `{vgname}`: {e}")
        return False

    util.SMlog(f"LVM metadata backed up in `{backup_file_path}`")
    return True
