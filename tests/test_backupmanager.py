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

from datetime import datetime
import unittest
import unittest.mock as mock
from pathlib import Path

from backupmanager import BackupManager

# ==============================================================================

FILES_TO_KEEP = 5
DST_PATH = Path("/tmp/backupmanager")

# ------------------------------------------------------------------------------

class MockBackup(BackupManager):
    def __init__(self):
        super().__init__(files_to_keep=FILES_TO_KEEP)

        self._backup_file_list = [
            (DST_PATH / str(i), datetime.fromtimestamp(i))
            for i in range(FILES_TO_KEEP * 2)
        ]

        self._backup_file_list.insert(
            0,
            (DST_PATH / f"retain.{0}", datetime.fromtimestamp(0))
        )
        self._backup_file_list.insert(
            0,
            (DST_PATH / f"remove.{0}", datetime.fromtimestamp(0))
        )

        last_file_idx = FILES_TO_KEEP * 2 - 1
        self._backup_file_list.append(
            (DST_PATH / f"retain.{last_file_idx}",
             datetime.fromtimestamp(last_file_idx))
        )
        self._backup_file_list.append(
            (DST_PATH / f"remove.{last_file_idx}",
             datetime.fromtimestamp(last_file_idx))
        )

        self._custom_file_retention_check_enabled = False

    # ----------------------------------
    # Backup file naming.
    # ----------------------------------

    @override
    def _backup_dir_path(self, _ctx):
        return DST_PATH

    @override
    def _format_backup_file_name(self, ctx, counter):
        if counter is not None:
            return f"{ctx}.{counter}"

        return ctx

    # ----------------------------------
    # Backup file listing.
    # ----------------------------------

    @override
    def _backup_files(self, _ctx):
        return iter(self._backup_file_list)

    # ----------------------------------
    # Retention ops.
    # ----------------------------------

    @override
    def _check_file_for_retention(self, file_path):
        if not self._custom_file_retention_check_enabled:
            return super()._check_file_for_retention(file_path)

        if file_path.name.startswith("retain"):
            return BackupManager.FileRetentionCheckResult.RETAIN
        elif file_path.name.startswith("remove"):
            return BackupManager.FileRetentionCheckResult.REMOVE

        return BackupManager.FileRetentionCheckResult.CHECK

    # ----------------------------------
    # Backup ops.
    # ----------------------------------

    @override
    def _do_backup(self, ctx):
        latest_backup_file = self._latest_backup_file(ctx)
        backup_time = int(latest_backup_file[1].timestamp()) + 1
        backup_file_path = DST_PATH / str(backup_time)

        self._backup_file_list.append(
            (backup_file_path, datetime.fromtimestamp(backup_time))
        )

        return backup_file_path

    # ----------------------------------
    # Test knobs.
    # ----------------------------------

    @property
    def backup_file_list(self):
        return self._backup_file_list

    def add_unsorted_backup_files(self):
        self._backup_file_list.insert(
            0,
            (DST_PATH / str(FILES_TO_KEEP), datetime.fromtimestamp(FILES_TO_KEEP))
        )

        self._backup_file_list.append(
            (DST_PATH / "0", datetime.fromtimestamp(0))
        )

    def remove_all_backups(self):
        self._backup_file_list.clear()

    def remove_backup(self, path):
        self._backup_file_list = [
            file for file in self.backup_file_list
            if file[0] != path
        ]

    def enable_custom_file_retention_check(self):
        self._custom_file_retention_check_enabled = True

    def disable_backups(self):
        self._enabled = False

    def disable_remove_expired_on_backup(self):
        self._remove_expired_on_backup = False

# ------------------------------------------------------------------------------

class TestBackupManager(unittest.TestCase):
    @override
    def setUp(self):
        self.backup = MockBackup()
        self.backup_name = "GLaDOS_first_boot"

    def test_next_backup_file_path(self):
        self.assertEqual(
            self.backup._next_backup_file_path(self.backup_name),
            DST_PATH / self.backup_name
        )

    @mock.patch("pathlib.Path.exists")
    def test_next_backup_file_path_with_counter(self, mock_path_exists):
        mock_path_exists.side_effect = [
            False,
            True, False,
            True, True, False,
        ]

        self.assertEqual(
            self.backup._next_backup_file_path(self.backup_name),
            DST_PATH / self.backup_name
        )
        self.assertEqual(
            self.backup._next_backup_file_path(self.backup_name),
            DST_PATH / f"{self.backup_name}.1"
        )
        self.assertEqual(
            self.backup._next_backup_file_path(self.backup_name),
            DST_PATH / f"{self.backup_name}.2"
        )

    def test_sorted_backup_files(self):
        self.backup.add_unsorted_backup_files()

        backup_files = self.backup._sorted_backup_files(self.backup_name)
        self.assertEqual(backup_files[0][1], datetime.fromtimestamp(0))
        self.assertEqual(backup_files[-1][1], datetime.fromtimestamp(9))

    def test_sorted_backup_files_reversed(self):
        self.backup.add_unsorted_backup_files()

        backup_files = self.backup._sorted_backup_files(self.backup_name, reverse=True)
        self.assertEqual(backup_files[0][1], datetime.fromtimestamp(9))
        self.assertEqual(backup_files[-1][1], datetime.fromtimestamp(0))

    def test_latest_backup_file(self):
        self.backup.add_unsorted_backup_files()

        backup_file = self.backup._latest_backup_file(self.backup_name)
        self.assertEqual(backup_file[1], datetime.fromtimestamp(9))

    def test_latest_backup_file_empty(self):
        self.backup.remove_all_backups()

        backup_file = self.backup._latest_backup_file(self.backup_name)
        self.assertEqual(backup_file[0], None)

    @mock.patch("backupmanager.datetime", autospec=True)
    def test_backup_age(self, mock_datetime):
        base_time = datetime.now()
        mock_datetime.now.return_value = base_time

        self.backup.add_unsorted_backup_files()

        backup_age = self.backup.backup_age(self.backup_name)
        self.assertEqual(
            backup_age,
            (base_time - datetime.fromtimestamp(9)).total_seconds()
        )

    def test_default_check_file_for_retention(self):
        self.assertEqual(
            self.backup._check_file_for_retention(DST_PATH / "0"),
            BackupManager.FileRetentionCheckResult.CHECK
        )

    def test_remove_expired(self):
        def side_effect_unlink(path):
            self.backup.remove_backup(path)

        with mock.patch("pathlib.Path.unlink", side_effect=side_effect_unlink, autospec=True):
            self.backup.remove_expired(self.backup_name)

        expected_files = [
            (DST_PATH / "7", datetime.fromtimestamp(7)),
            (DST_PATH / "8", datetime.fromtimestamp(8)),
            (DST_PATH / "9", datetime.fromtimestamp(9)),
            (DST_PATH / "retain.9", datetime.fromtimestamp(9)),
            (DST_PATH / "remove.9", datetime.fromtimestamp(9)),
        ]

        self.assertListEqual(self.backup.backup_file_list, expected_files)

    def test_remove_expired_with_custom_retention(self):
        self.backup.enable_custom_file_retention_check()

        def side_effect_unlink(path):
            self.backup.remove_backup(path)

        with mock.patch("pathlib.Path.unlink", side_effect=side_effect_unlink, autospec=True):
            self.backup.remove_expired(self.backup_name)

        expected_files = [
            (DST_PATH / "retain.0", datetime.fromtimestamp(0)),
            (DST_PATH / "6", datetime.fromtimestamp(6)),
            (DST_PATH / "7", datetime.fromtimestamp(7)),
            (DST_PATH / "8", datetime.fromtimestamp(8)),
            (DST_PATH / "9", datetime.fromtimestamp(9)),
            (DST_PATH / "retain.9", datetime.fromtimestamp(9)),
        ]

        self.assertListEqual(self.backup.backup_file_list, expected_files)

    def test_do_backup(self):
        self.assertEqual(
            self.backup._do_backup(self.backup_name),
            DST_PATH / "10"
        )

    @mock.patch.object(MockBackup, "_do_backup")
    @mock.patch.object(MockBackup, "remove_expired")
    def test_try_backup(self, mock_remove_expired, mock_do_backup):
        self.assertTrue(self.backup.try_backup(self.backup_name))

        mock_do_backup.assert_called_once()
        mock_remove_expired.assert_called_once()

    @mock.patch.object(MockBackup, "_do_backup")
    @mock.patch.object(MockBackup, "remove_expired")
    def test_try_backup_without_remove_expired(self, mock_remove_expired, mock_do_backup):
        self.backup.disable_remove_expired_on_backup()
        self.assertTrue(self.backup.try_backup(self.backup_name))

        mock_do_backup.assert_called_once()
        mock_remove_expired.assert_not_called()

    @mock.patch.object(MockBackup, "_do_backup")
    def test_try_backup_failure(self, mock_do_backup):
        mock_do_backup.side_effect = OSError()
        self.assertFalse(self.backup.try_backup(self.backup_name))

    def test_try_backup_disabled(self):
        self.backup.disable_backups()
        self.assertFalse(self.backup.try_backup(self.backup_name))
