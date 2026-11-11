from sm_typing import override

import unittest
import unittest.mock as mock

import scsiutil

import testlib


class Test_sg_readcap(unittest.TestCase):

    def verify_sg_readcap(self, doexec, expected_result):
        result = scsiutil.sg_readcap('/dev/sda')
        doexec.assert_called_with(['/usr/bin/sg_readcap', '-b', '/dev/sda'])
        self.assertEqual(result, expected_result)

    @mock.patch('util.doexec', autospec=True)
    def test_sg_readcap_10(self, doexec):
        fake_out = "0x3a376030 0x200\n"
        doexec.return_value = (0, fake_out, '')
        self.verify_sg_readcap(doexec, 500074307584)

    # Can't use autospec due to http://bugs.python.org/issue17826
    @mock.patch('util.doexec')
    def test_capacity_data_changed_rc6(self, doexec):
        fake_out = "0x3a376030 0x200\n"
        doexec.side_effect = [(6, 'something else', ''), (0, fake_out, '')]
        self.verify_sg_readcap(doexec, 500074307584)

    @mock.patch('util.doexec', autospec=True)
    def test_sg_readcap_16(self, doexec):
        fake_out = ("READ CAPACITY (10) indicates device capacity too large\n"
                    "now trying 16 byte cdb variant\n"
                    "0x283d8e000 0x200\n")
        doexec.return_value = (0, fake_out, '')
        self.verify_sg_readcap(doexec, 5530605060096)

    @testlib.with_context
    def test_refreshdev(self, context):
        adapter = context.add_adapter(testlib.SCSIAdapter())
        adapter.add_disk()

        scsiutil.refreshdev(["/dev/sda"])


class TestGetDevicesByScsciId(unittest.TestCase):
    @override
    def setUp(self) -> None:
        self.addCleanup(mock.patch.stopall)

        listdir_patcher = mock.patch('os.listdir')
        self.mock_listdir = listdir_patcher.start()
        realpath_patcher = mock.patch('os.path.realpath')
        self.mock_realpath = realpath_patcher.start()

    def test_get_devices_by_SCSIid_no_devices(self):
        self.mock_listdir.return_value = []

        # Act
        paths = scsiutil.get_devices_by_SCSIid("scsiid")

        # Assert
        self.assertListEqual([], paths)

    def test_get_devices_by_SCSIid_devices(self):
        self.mock_listdir.return_value = ['sda', 'sdc', 'sday']
        path_map = {
            '/dev/disk/by-scsid/scsiid/sda': '/dev/sda',
            '/dev/disk/by-scsid/scsiid/sdc': '/dev/sdc',
            '/dev/disk/by-scsid/scsiid/sday': '/dev/sday'
        }
        self.mock_realpath.side_effect = path_map.get

        # Act
        paths = scsiutil.get_devices_by_SCSIid("scsiid")

        # Assert
        print(paths)
        self.assertListEqual(list(path_map.values()), paths)

    def test_get_devices_by_SCSIid_different_target(self):
        self.mock_listdir.return_value = ['1', '2', '3']
        path_map = {
            '/dev/disk/by-scsid/scsiid/1': '/dev/sda',
            '/dev/disk/by-scsid/scsiid/2': '/dev/sdc',
            '/dev/disk/by-scsid/scsiid/3': '/dev/sday'
        }
        self.mock_realpath.side_effect = path_map.get

        # Act
        paths = scsiutil.get_devices_by_SCSIid("scsiid")

        # Assert
        print(paths)
        self.assertListEqual(list(path_map.values()), paths)

    @mock.patch('scsiutil.getSCSIid', autospec=True)
    @mock.patch('scsiutil.os.path.exists', autospec=True)
    @mock.patch('scsiutil.glob.glob', autospec=True)
    def test_lun_present_on_host(self, mock_glob, mock_exists, mock_getid):
        mock_glob.return_value = ['/dev/disk/by-scsibus/scsiid-13:0:0:214']
        mock_exists.return_value = True
        mock_getid.return_value = "scsiid"

        self.assertTrue(scsiutil.lun_present_on_host("scsiid", "13"))
        mock_glob.assert_called_with('/dev/disk/by-scsibus/scsiid-13:*')
        mock_getid.assert_called_with('/dev/disk/by-scsibus/scsiid-13:0:0:214')

    @mock.patch('scsiutil.getSCSIid', autospec=True)
    @mock.patch('scsiutil.os.path.exists', autospec=True)
    @mock.patch('scsiutil.glob.glob', autospec=True)
    def test_lun_present_on_host_no_device(self, mock_glob, mock_exists, mock_getid):
        mock_glob.return_value = []

        self.assertFalse(scsiutil.lun_present_on_host("scsiid", "13"))
        mock_getid.assert_not_called()

    @mock.patch('scsiutil.getSCSIid', autospec=True)
    @mock.patch('scsiutil.os.path.exists', autospec=True)
    @mock.patch('scsiutil.glob.glob', autospec=True)
    def test_lun_present_on_host_dangling_link(self, mock_glob, mock_exists, mock_getid):
        mock_glob.return_value = ['/dev/disk/by-scsibus/scsiid-13:0:0:214']
        mock_exists.return_value = False

        self.assertFalse(scsiutil.lun_present_on_host("scsiid", "13"))
        mock_getid.assert_not_called()

    @mock.patch('scsiutil.getSCSIid', autospec=True)
    @mock.patch('scsiutil.os.path.exists', autospec=True)
    @mock.patch('scsiutil.glob.glob', autospec=True)
    def test_lun_present_on_host_other_volume(self, mock_glob, mock_exists, mock_getid):
        """The link is stale: the LUN behind it is another volume now"""
        mock_glob.return_value = ['/dev/disk/by-scsibus/scsiid-13:0:0:214']
        mock_exists.return_value = True
        mock_getid.return_value = "otherid"

        self.assertFalse(scsiutil.lun_present_on_host("scsiid", "13"))

    @mock.patch('scsiutil.getSCSIid', autospec=True)
    @mock.patch('scsiutil.os.path.exists', autospec=True)
    @mock.patch('scsiutil.glob.glob', autospec=True)
    def test_lun_present_on_host_dead_device(self, mock_glob, mock_exists, mock_getid):
        """The link is stale: the LUN behind it is gone, the query fails"""
        mock_glob.return_value = ['/dev/disk/by-scsibus/scsiid-13:0:0:214']
        mock_exists.return_value = True
        mock_getid.side_effect = scsiutil.util.CommandException(1)

        self.assertFalse(scsiutil.lun_present_on_host("scsiid", "13"))

    @mock.patch('scsiutil.getSCSIid', autospec=True)
    @mock.patch('scsiutil.os.path.exists', autospec=True)
    @mock.patch('scsiutil.glob.glob', autospec=True)
    def test_lun_present_on_host_stale_and_current(self, mock_glob, mock_exists, mock_getid):
        """A stale link and the LUN's current device: the current one counts"""
        mock_glob.return_value = ['/dev/disk/by-scsibus/scsiid-13:0:0:214',
                                  '/dev/disk/by-scsibus/scsiid-13:0:0:215']
        mock_exists.return_value = True
        mock_getid.side_effect = ["otherid", "scsiid"]

        self.assertTrue(scsiutil.lun_present_on_host("scsiid", "13"))
