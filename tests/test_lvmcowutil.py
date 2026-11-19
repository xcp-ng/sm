import unittest
import unittest.mock as mock

from cowutil import CowImageInfo
from lvmcache import LVInfo, LVMCache
from lvmcowutil import LvmCowUtil


@mock.patch("lvmcowutil.getCowUtil")
class TestGetVDIInfo(unittest.TestCase):
    def make_cache(self, lv_exists):
        cache = mock.create_autospec(LVMCache, instance=True)
        cache.vgName = "VG_XenStorage-sr"
        cache.getLVInfo.return_value = {
            name: LVInfo(name) for name in ("QCOW2-a", "QCOW2-b", "VHD-c")
        }
        cache.checkLV.return_value = lv_exists
        return cache

    def test_lv_disappeared_during_scan(self, getCowUtil):
        # No image info for "b": its LV was removed after the LV listing.
        getCowUtil.return_value.getAllInfoFromVG.return_value = {
            "a": CowImageInfo("a"),
            "c": CowImageInfo("c"),
        }
        cache = self.make_cache(lv_exists=False)

        vdis = LvmCowUtil.getVDIInfo(cache)

        self.assertEqual(sorted(vdis), ["a", "c"])
        cache.refresh.assert_called_once_with()
        cache.checkLV.assert_called_once_with("QCOW2-b")

    def test_image_info_missing(self, getCowUtil):
        getCowUtil.return_value.getAllInfoFromVG.return_value = {
            "a": CowImageInfo("a"),
            "c": CowImageInfo("c"),
        }
        cache = self.make_cache(lv_exists=True)

        vdis = LvmCowUtil.getVDIInfo(cache)

        self.assertEqual(sorted(vdis), ["a", "b", "c"])
        self.assertTrue(vdis["b"].scanError)
        self.assertFalse(vdis["a"].scanError)
