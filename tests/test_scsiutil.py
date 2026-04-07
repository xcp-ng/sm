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

    def setUp(self):
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
