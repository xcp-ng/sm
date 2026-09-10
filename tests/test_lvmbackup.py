from sm_typing import override

import filecmp
import os
import tempfile
import unittest
import unittest.mock as mock

import lvmbackup


class TestBackupVg(unittest.TestCase):
    MOCKED_FILES_TO_KEEP = 5
    MOCKED_TIME = "20260908_155410"

    @override
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.test_dir.cleanup)

        self.dst_path = os.path.join(self.test_dir.name, "sm-backups")
        self.src_path = os.path.join(self.test_dir.name, "backup")
        os.makedirs(self.src_path)
        os.makedirs(self.dst_path)

        mock.patch("lvmbackup.DST_PATH", self.dst_path).start()
        mock.patch("lvmbackup.SRC_PATH", self.src_path).start()
        mock.patch("lvmbackup.FILES_TO_KEEP", self.MOCKED_FILES_TO_KEEP).start()
        self.addCleanup(mock.patch.stopall)

        self.vgname = "VG_XenStorage-8c1e6de6-d35c-755d-82a2-1e7d1c903190"
        with open(os.path.join(self.src_path, self.vgname), "w") as f:
            f.write(f"Some metadata for VG {self.vgname}")

    def test_vg_backup_dir_path(self):
        self.assertEqual(
            lvmbackup._vg_backup_dir_path(self.vgname),
            os.path.join(self.dst_path, self.vgname)
        )

    @mock.patch("time.strftime")
    def test_next_backup_file_path(self, mock_strftime):
        mock_strftime.return_value = self.MOCKED_TIME

        self.assertEqual(
            lvmbackup._next_backup_file_path(self.dst_path),
            os.path.join(self.dst_path, f"{self.MOCKED_TIME}.vg")
        )

    @mock.patch("time.strftime")
    @mock.patch("os.path.lexists")
    def test_next_backup_file_path_with_counter(self, mock_lexists, mock_strftime):
        mock_strftime.return_value = self.MOCKED_TIME

        mock_lexists.side_effect = [
            False,
            True, False,
            True, True, False,
        ]

        self.assertEqual(
            lvmbackup._next_backup_file_path(self.dst_path),
            os.path.join(self.dst_path, f"{self.MOCKED_TIME}.vg")
        )
        self.assertEqual(
            lvmbackup._next_backup_file_path(self.dst_path),
            os.path.join(self.dst_path, f"{self.MOCKED_TIME}.1.vg")
        )
        self.assertEqual(
            lvmbackup._next_backup_file_path(self.dst_path),
            os.path.join(self.dst_path, f"{self.MOCKED_TIME}.2.vg")
        )

    @mock.patch("lvmbackup._next_backup_file_path")
    def test_do_backup(self, mock_next_backup_file_path):
        backup_file_path = os.path.join(self.dst_path, self.vgname, "do_backup.vg")
        mock_next_backup_file_path.return_value = backup_file_path

        self.assertEqual(lvmbackup._do_backup(self.vgname), backup_file_path)
        self.assertTrue(os.path.lexists(backup_file_path))
        self.assertTrue(filecmp.cmp(os.path.join(self.src_path, self.vgname), backup_file_path, shallow=False))

    @mock.patch("lvmbackup._vg_backup_dir_path")
    def test_remove_expired(self, mock_vg_backup_dir_path):
        mock_vg_backup_dir_path.return_value = self.dst_path

        generated_files = [
            os.path.join(self.dst_path, f"{i}.vg")
            for i in range(self.MOCKED_FILES_TO_KEEP + 1)
        ]

        for i, generated_file_path in enumerate(generated_files):
            with open(generated_file_path, "w") as f:
                f.write(f"Some metadata for VG {self.vgname}")

            os.utime(generated_file_path, (i, i))

        lvmbackup._remove_expired(self.vgname)

        current_files = [os.path.join(self.dst_path, file_name) for file_name in os.listdir(self.dst_path)]
        expected_files = generated_files[-self.MOCKED_FILES_TO_KEEP:]

        current_files.sort()
        expected_files.sort()

        self.assertListEqual(expected_files, current_files)

    @mock.patch("lvmbackup._do_backup")
    @mock.patch("lvmbackup._remove_expired")
    def test_backup_vg(self, mock_remove_expired, mock_do_backup):
        self.assertTrue(lvmbackup.backup_vg(self.vgname))

        mock_do_backup.assert_called_once()
        mock_remove_expired.assert_called_once()

    @mock.patch("lvmbackup._do_backup")
    def test_backup_vg_failure(self, mock_do_backup):
        mock_do_backup.side_effect = OSError()
        self.assertFalse(lvmbackup.backup_vg(self.vgname))

    @mock.patch("lvmbackup.ENABLED", False)
    def test_backup_vg_disabled(self):
        self.assertFalse(lvmbackup.backup_vg(self.vgname))
