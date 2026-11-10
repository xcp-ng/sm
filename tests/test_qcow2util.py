import os
import stat
import struct
import unittest
from unittest import mock

import qcow2util


def make_qcow2_header(l1_size=1, l1_table_offset=104) -> bytes:
    """Minimal valid v2 qcow2 header, same layout as _read_qcow2_header."""
    return struct.pack(
        ">IIQIIQIIQQIIQ",
        qcow2util.QCowUtil.QCOW2_MAGIC,   # magic
        2,                                # version
        0,                                # backing_file_offset
        0,                                # backing_file_size
        16,                               # cluster_bits
        64 * 1024 * 1024,                 # virtual disk size
        0,                                # crypt_method
        l1_size,                          # l1_size
        l1_table_offset,                  # l1_table_offset
        0,                                # refcount_table_offset
        0,                                # refcount_table_clusters
        0,                                # nb_snapshots
        0,                                # snapshots_offset
    )


class TestQCowUtilKillData(unittest.TestCase):
    """killData must not ftruncate() a block device (qcow2 on a LVM LV):
    ftruncate on a block device returns EINVAL. On a regular file
    (FileSR) the truncate must still happen."""

    LV_PATH = "/dev/VG_XenStorage-sr/QCOW2-vdi"

    def test_kill_data_on_block_device_skips_truncate(self):
        with mock.patch("qcow2util.os.stat", autospec=True) as mock_stat, \
                mock.patch("builtins.open", mock.mock_open(
                    read_data=make_qcow2_header())) as mock_open:
            mock_stat.return_value = os.stat_result(
                (stat.S_IFBLK, 0, 0, 0, 0, 0, 0, 0, 0, 0))

            qcow2util.QCowUtil().killData(self.LV_PATH)

            file_mock = mock_open()
            file_mock.write.assert_called_once_with(b"\x00" * 8)
            file_mock.truncate.assert_not_called()

    def test_kill_data_on_regular_file_still_truncates(self):
        with mock.patch("qcow2util.os.stat", autospec=True) as mock_stat, \
                mock.patch("builtins.open", mock.mock_open(
                    read_data=make_qcow2_header())) as mock_open:
            mock_stat.return_value = os.stat_result(
                (stat.S_IFREG, 0, 0, 0, 0, 0, 0, 0, 0, 0))

            qcow2util.QCowUtil().killData("/mnt/SR-TEST/vdi.qcow2")

            file_mock = mock_open()
            file_mock.write.assert_called_once_with(b"\x00" * 8)
            file_mock.truncate.assert_called_once_with(104 + 8)