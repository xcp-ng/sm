import os
import unittest
import unittest.mock as mock

import SR


class TestLVMDeviceForTheLoadedSR(unittest.TestCase):
    """SR.__init__ points LVM_DEVICE at the SR's own LUN, and never leaves another SR's LUN in place."""

    def create_SR(self, dconf):
        srcmd = mock.Mock()
        srcmd.dconf = dconf
        srcmd.params = {'command': 'sr_scan', 'device_config': dconf}
        return SR.SR(srcmd, "some SR UUID")

    @mock.patch.dict(os.environ, {'LVM_DEVICE': '/dev/disk/by-scsid/other'})
    def test_sr_with_scsiid_sets_its_own_device(self):
        self.create_SR({'SCSIid': 'abc'})
        self.assertEqual(os.environ['LVM_DEVICE'], '/dev/disk/by-scsid/abc')

    @mock.patch.dict(os.environ, {'LVM_DEVICE': '/dev/disk/by-scsid/other'})
    def test_sr_without_scsiid_unsets_another_srs_device(self):
        self.create_SR({'device': '/dev/sda'})
        self.assertNotIn('LVM_DEVICE', os.environ)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_sr_without_scsiid_and_no_device_set(self):
        self.create_SR({'device': '/dev/sda'})
        self.assertNotIn('LVM_DEVICE', os.environ)


if __name__ == '__main__':
    unittest.main()
