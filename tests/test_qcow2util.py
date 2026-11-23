from sm_typing import override

import unittest
import unittest.mock as mock

import qcow2util

SIZE_VIRT = 64 * 1024 * 1024 * 1024


class TestMeasure(unittest.TestCase):
    """qemu-img measure is an upper bound for both L2 layouts"""

    def calc_overhead(self, *args):
        util = qcow2util.QCowUtil()
        with mock.patch.object(util, "_ioretry",
                               return_value='{"required": 19136512, "fully-allocated": 68738613248}') \
                as mock_ioretry:
            self.assertEqual(19136512, util.calcOverheadEmpty(SIZE_VIRT, *args))
        return mock_ioretry.call_args[0][0]

    def test_extended_l2(self):
        self.assertEqual(
            ["/usr/bin/qemu-img", "measure", "-O", "qcow2", "--output", "json",
             "-o", "cluster_size=65536,extended_l2=on", "--size", str(SIZE_VIRT)],
            self.calc_overhead())
        self.assertIn("cluster_size=16384,extended_l2=on", self.calc_overhead(16 * 1024))

    def test_cluster_too_small_for_extended_l2(self):
        self.assertIn("cluster_size=8192", self.calc_overhead(8 * 1024))
