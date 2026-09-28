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

from sm_typing import override

import filecmp
import os
import tempfile
import unittest
import unittest.mock as mock
from datetime import datetime
from pathlib import Path

from lvmbackup import LVMMetadataBackup

# ==============================================================================

class TestLvmBackup(unittest.TestCase):
    MOCKED_FILES_TO_KEEP = 5
    MOCKED_TIME = "20260908_155410"

    @override
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.test_dir.cleanup)

        self.src_path = Path(self.test_dir.name) / "src"
        self.dst_path = Path(self.test_dir.name) / "dst"
        self.src_path.mkdir(parents=True)
        self.dst_path.mkdir(parents=True)

        mock.patch("lvmbackup.DST_PATH", self.dst_path).start()
        mock.patch("lvmbackup.SRC_PATH", self.src_path).start()
        mock.patch("lvmbackup.FILES_TO_KEEP", self.MOCKED_FILES_TO_KEEP).start()
        self.addCleanup(mock.patch.stopall)

        self.vgname = "VG_XenStorage-8c1e6de6-d35c-755d-82a2-1e7d1c903190"
        with (self.src_path / self.vgname).open("w") as f:
            f.write(f"Some metadata for VG {self.vgname}")

        self.backup = LVMMetadataBackup()

    def test_backup_dir_path(self):
        self.assertEqual(
            self.backup._backup_dir_path(self.vgname),
            self.dst_path / self.vgname
        )

    @mock.patch("time.strftime")
    def test_format_backup_file_name(self, mock_strftime):
        mock_strftime.return_value = self.MOCKED_TIME

        self.assertEqual(
            self.backup._format_backup_file_name(self.vgname, None),
            f"{self.MOCKED_TIME}.vg"
        )

    @mock.patch("time.strftime")
    def test_format_backup_file_name_with_counter(self, mock_strftime):
        mock_strftime.return_value = self.MOCKED_TIME

        self.assertEqual(
            self.backup._format_backup_file_name(self.vgname, 2),
            f"{self.MOCKED_TIME}.2.vg"
        )

    def test_backup_files(self):
        backup_file_path = self.backup._next_backup_file_path(self.vgname)
        backup_file_path.parent.mkdir(parents=True, exist_ok=True)

        with backup_file_path.open("w") as f:
            f.write(f"Some metadata for VG {self.vgname}")

        os.utime(backup_file_path, (42, 42))

        expected_backup_files = [(backup_file_path, datetime.fromtimestamp(42))]

        backup_files = list(self.backup._backup_files(self.vgname))
        self.assertListEqual(backup_files, expected_backup_files)

    @mock.patch("lvmbackup.LVMMetadataBackup._next_backup_file_path")
    def test_do_backup(self, mock_next_backup_file_path):
        backup_file_path = self.dst_path / self.vgname / "do_backup.vg"
        mock_next_backup_file_path.return_value = backup_file_path

        self.assertEqual(self.backup._do_backup(self.vgname), backup_file_path)
        self.assertTrue(backup_file_path.exists())
        self.assertTrue(filecmp.cmp(self.src_path / self.vgname, backup_file_path, shallow=False))

    @mock.patch("lvmbackup.LVMMetadataBackup._backup_dir_path")
    def test_remove_vg_backups(self, mock_backup_dir_path):
        mock_backup_dir_path.return_value = self.dst_path

        self.assertTrue(self.dst_path.parent.is_dir())
        self.assertTrue(self.dst_path.is_dir())

        self.backup.remove_vg_backups(self.vgname)

        self.assertTrue(self.dst_path.parent.is_dir())
        self.assertFalse(self.dst_path.is_dir())

    @mock.patch("shutil.rmtree")
    def test_remove_vg_backups_failure(self, mock_rmtree):
        mock_rmtree.side_effect = FileNotFoundError()
        self.backup.remove_vg_backups(self.vgname)
