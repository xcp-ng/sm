from sm_typing import override

import unittest.mock as mock
import HBASR
import unittest
import SR
from SRCommand import SRCommand
from DummySR import DRIVER_INFO
import xml.dom.minidom
import util
import xs_errors

import errno
import io
import os
import uuid


def imp_fake_probe():
    dom = xml.dom.minidom.Document()
    hbalist = dom.createElement("HBAInfoList")
    dom.appendChild(hbalist)

    for host in ["host1", "host2"]:
        hbainfo = dom.createElement("HBAInfo")
        hbalist.appendChild(hbainfo)

        sname = "nvme_special"
        entry = dom.createElement("model")
        hbainfo.appendChild(entry)
        textnode = dom.createTextNode(sname)
        entry.appendChild(textnode)

        nname = "0x200000e08b18208b"
        nname = util.make_WWN(nname)
        entry = dom.createElement("nodeWWN")
        hbainfo.appendChild(entry)
        textnode = dom.createTextNode(nname)
        entry.appendChild(textnode)

        port = dom.createElement("Port")
        hbainfo.appendChild(port)

        pname = "0x500143802426baf4"
        pname = util.make_WWN(pname)
        entry = dom.createElement("portWWN")
        port.appendChild(entry)
        textnode = dom.createTextNode(pname)
        entry.appendChild(textnode)

        state = "toast"
        entry = dom.createElement("state")
        port.appendChild(entry)
        textnode = dom.createTextNode(state)
        entry.appendChild(textnode)

        entry = dom.createElement("deviceName")
        port.appendChild(entry)
        textnode = dom.createTextNode("/sys/class/scsi_host/%s" % host)
        entry.appendChild(textnode)

    return dom.toxml()


def fake_probe(self):
    return imp_fake_probe()


class TestHBASR(unittest.TestCase):
    @override
    def setUp(self):
        self.addCleanup(mock.patch.stopall)

        adapters_patcher = mock.patch(
            "HBASR.devscan.adapters", autospec=True)
        self.mock_devscan_adapters = adapters_patcher.start()

        mpath_handle_patcher = mock.patch(
            "HBASR.SR.SR._mpathHandle", autospec=True)
        self.mock_mpath_handle = mpath_handle_patcher.start()

        rootdev_patcher = mock.patch(
            'HBASR.devscan.util.getrootdevID', autospec=True)
        self.mock_rootdevid = rootdev_patcher.start()

        glob_patcher = mock.patch('HBASR.devscan.glob.glob', autospec=True)
        self.mock_glob = glob_patcher.start()

        real_path_basename = os.path.basename
        real_path_join = os.path.join
        os_path_patcher = mock.patch('HBASR.devscan.os.path', autospec=True)
        self.mock_os_path = os_path_patcher.start()
        self.mock_os_path.basename = real_path_basename
        self.mock_os_path.join = real_path_join

        smlog_patcher = mock.patch('HBASR.util.SMlog', autospec=True)
        self.mock_sm_log = smlog_patcher.start()

    def make_sr_cmd(self, command='sr_probe'):
        sr_cmd = mock.Mock(spec=SRCommand(DRIVER_INFO))
        sr_cmd.dconf = {}
        sr_cmd.params = {'command': command}
        return sr_cmd

    def test_handles(self):
        sr_uuid = str(uuid.uuid4())
        sr_cmd = self.make_sr_cmd()

        sr = HBASR.HBASR(sr_cmd, sr_uuid)

        self.assertFalse(sr.handles("blah"))
        self.assertTrue(sr.handles("hba"))

    def test_load(self):
        sr_uuid = 123
        sr_cmd = self.make_sr_cmd()

        sr = HBASR.HBASR(sr_cmd, sr_uuid)
        sr.load(sr_uuid)

        self.assertEqual(sr.sr_vditype, 'phy')
        self.assertEqual(sr.type, 'any')
        self.assertFalse(sr.attached)
        self.assertEqual(sr.procname, "")
        self.assertEqual(sr.devs, {})

        sr.dconf = {"type": None}
        sr.load(sr_uuid)

        self.assertEqual(sr.sr_vditype, 'phy')
        self.assertEqual(sr.type, 'any')
        self.assertFalse(sr.attached)
        self.assertEqual(sr.procname, "")
        self.assertEqual(sr.devs, {})

        sr.dconf = {"type": "blah"}
        sr.load(sr_uuid)

        self.assertEqual(sr.sr_vditype, 'phy')
        self.assertEqual(sr.type, 'blah')
        self.assertFalse(sr.attached)
        self.assertEqual(sr.procname, "")
        self.assertEqual(sr.devs, {})

    @mock.patch('HBASR.scsiutil.cacheSCSIidentifiers', autospec=True)
    def test__intit_bhadict_already_init(self, mock_cacheSCSIidentifiers):
        sr_uuid = str(uuid.uuid4())
        sr_cmd = self.make_sr_cmd()
        sr = HBASR.HBASR(sr_cmd, sr_uuid)
        sr.hbas = {"Pitt": "The elder"}
        sr._init_hbadict()
        self.assertEqual(mock_cacheSCSIidentifiers.call_count, 0)
        self.assertEqual(self.mock_devscan_adapters.call_count, 0)

    @mock.patch('HBASR.scsiutil.cacheSCSIidentifiers', autospec=True)
    def test__init_hbadict(self, mock_cacheSCSIidentifiers):
        sr_uuid = str(uuid.uuid4())
        sr_cmd = self.make_sr_cmd()
        sr = HBASR.HBASR(sr_cmd, sr_uuid)
        sr.type = "foo"
        self.mock_devscan_adapters.return_value = {
            "devs": "toaster", "adt": []}
        sr._init_hbadict()
        self.mock_devscan_adapters.assert_called_with(filterstr="foo")
        self.assertEqual(mock_cacheSCSIidentifiers.call_count, 0)
        self.assertEqual(self.mock_devscan_adapters.call_count, 1)
        self.assertEqual(sr.hbas, [])
        self.assertEqual(sr.hbadict, "toaster")

        mock_cacheSCSIidentifiers.call_count = 0
        self.mock_devscan_adapters.call_count = 0
        mock_cacheSCSIidentifiers.return_value = "123445"
        sr2 = HBASR.HBASR(sr_cmd, sr_uuid)
        sr2.type = "foo"
        self.mock_devscan_adapters.return_value = {"devs": "toaster",
                                                   "adt": ["dev1", "dev2"]}
        sr2._init_hbadict()
        self.assertEqual(mock_cacheSCSIidentifiers.call_count, 1)
        self.assertEqual(self.mock_devscan_adapters.call_count, 1)
        self.assertEqual(sr2.hbas, ["dev1", "dev2"])
        self.assertEqual(sr2.hbadict, "toaster")
        self.assertTrue(sr2.attached)
        self.assertEqual(sr2.devs, "123445")

    @mock.patch('HBASR.HBASR._probe_hba', autospec=True)
    @mock.patch('HBASR.xml.dom.minidom.parseString', autospec=True)
    def test__init_hbahostname_assert(self, mock_parseString, mock_probe_hba):
        sr_uuid = str(uuid.uuid4())
        sr_cmd = self.make_sr_cmd()
        sr = HBASR.HBASR(sr_cmd, sr_uuid)
        mock_probe_hba.return_value = "blah"
        mock_parseString.side_effect = Exception("bad xml")
        with self.assertRaises(xs_errors.SROSError) as cm:
            sr._init_hba_hostname()
        self.assertEqual(str(cm.exception),
                         "Unable to parse XML "
                         "[opterr=HBA Host WWN scanning failed]")

    @mock.patch('HBASR.HBASR._probe_hba', fake_probe)
    def test__init_hbahostname(self):
        sr_uuid = str(uuid.uuid4())
        sr_cmd = self.make_sr_cmd()
        sr = HBASR.HBASR(sr_cmd, sr_uuid)
        res = sr._init_hba_hostname()
        self.assertEqual(res, "20-00-00-e0-8b-18-20-8b")

    @mock.patch('HBASR.HBASR._probe_hba', autospec=True)
    @mock.patch('HBASR.xml.dom.minidom.parseString', autospec=True)
    def test__init_hbas_assert(self, mock_parseString, mock_probe_hba):
        sr_uuid = str(uuid.uuid4())
        sr_cmd = self.make_sr_cmd()
        sr = HBASR.HBASR(sr_cmd, sr_uuid)
        mock_probe_hba.return_value = "blah"
        mock_parseString.side_effect = Exception("bad xml")
        with self.assertRaises(xs_errors.SROSError) as cm:
            sr._init_hbas()
        self.assertEqual(str(cm.exception),
                         "Unable to parse XML "
                         "[opterr=HBA scanning failed]")

    @mock.patch('HBASR.HBASR._probe_hba', fake_probe)
    def test__init_hbas(self):
        sr_uuid = str(uuid.uuid4())
        sr_cmd = self.make_sr_cmd()
        sr = HBASR.HBASR(sr_cmd, sr_uuid)
        res = sr._init_hbas()
        self.assertEqual(res, {'host2': '50-01-43-80-24-26-ba-f4',
                               'host1': '50-01-43-80-24-26-ba-f4'})

    @mock.patch('HBASR.util.pread', autospec=True)
    def test__probe_hba_assert(self, mock_pread):
        sr_uuid = str(uuid.uuid4())
        sr_cmd = self.make_sr_cmd()
        sr = HBASR.HBASR(sr_cmd, sr_uuid)
        mock_pread.side_effect = Exception("bad")
        with self.assertRaises(xs_errors.SROSError) as cm:
            sr._probe_hba()
        self.assertEqual(str(cm.exception),
                         "Unable to parse XML "
                         "[opterr=HBA probe failed]")

    @mock.patch('HBASR.util.pread', autospec=True)
    @mock.patch('HBASR.util.listdir', autospec=True)
    def test__probe_hba(self, mock_listdir, mock_pread):
        sr_uuid = str(uuid.uuid4())
        sr_cmd = self.make_sr_cmd()
        sr = HBASR.HBASR(sr_cmd, sr_uuid)
        mock_listdir.return_value = iter(["host1", "host2"])
        # Output of preads sliced by _probe_hba to remove newlines.
        mock_pread.side_effect = iter(["nvme_special\n",
                                  "0x200000e08b18208b\n",
                                  "0x500143802426baf4\n",
                                  "toast\n",
                                  "nvme_special\n",
                                  "0x200000e08b18208b\n",
                                  "0x500143802426baf4\n",
                                  "toast\n"])
        res = sr._probe_hba()
        self.assertEqual(res, imp_fake_probe())

    def test_attach(self):
        sr_uuid = str(uuid.uuid4())
        sr_cmd = self.make_sr_cmd()
        sr = HBASR.HBASR(sr_cmd, sr_uuid)
        sr.attach(1234)
        self.assertEqual(self.mock_mpath_handle.call_count, 1)

    def test_print_devs_no_devs(self):
        # Arrange
        sr_uuid = str(uuid.uuid4())
        sr_cmd = self.make_sr_cmd()
        sr = HBASR.HBASR(sr_cmd, sr_uuid)

        # Act
        dev_str = sr.print_devs()

        # Assert
        self.assertEqual(dev_str,
                         '<?xml version="1.0" ?>\n<Devlist/>\n')

    def test_print_devs_powerflex_error(self):
        sr_uuid = str(uuid.uuid4())
        sr_cmd = self.make_sr_cmd()
        sr = HBASR.HBASR(sr_cmd, sr_uuid)
        self.mock_glob.return_value = [
            '/dev/disk/by-scsid/emc-vol-19ab00bee9314e0f-894b409a00000000'
        ]
        self.mock_os_path.realpath.side_effect = OSError(errno.ENOENT)

        # Act
        dev_str = sr.print_devs()

        # Assert
        self.assertEqual(dev_str,
                         '<?xml version="1.0" ?>\n<Devlist/>\n')

    def test_print_devs_powerflex(self):
        # Arrange
        sr_uuid = str(uuid.uuid4())
        sr_cmd = self.make_sr_cmd()
        sr = HBASR.HBASR(sr_cmd, sr_uuid)
        self.mock_glob.return_value = [
            '/dev/disk/by-scsid/emc-vol-19ab00bee9314e0f-894b409a00000000'
        ]
        self.mock_os_path.realpath.return_value = '/dev/scinia'

        file_data = {
            'size': 2 * 1024 * 1024,
            'logical_block_size': 512
        }

        def open(filename):
            basename = os.path.basename(filename.strip())
            file_contents = io.StringIO()
            file_contents.write(f'{file_data[basename]}\n')

            file_contents.seek(0)
            return file_contents

        # Act
        with mock.patch("builtins.open") as mock_open:
            mock_open.side_effect = open

            dev_str = sr.print_devs()

        # Assert
        dom = xml.dom.minidom.Document()
        dl = dom.createElement("Devlist")
        dom.appendChild(dl)
        bd = dom.createElement("BlockDevice")
        dl.appendChild(bd)
        device_data = {
            'SCSIid': 'emc-vol-19ab00bee9314e0f-894b409a00000000',
            'path': '/dev/scinia',
            'vendor': 'emc',
            'size': 1073741824}
        for k, v in device_data.items():
            entry = dom.createElement(str(k))
            bd.appendChild(entry)
            text_node = dom.createTextNode(str(v))
            entry.appendChild(text_node)

        self.assertEqual(dev_str, dom.toprettyxml())
        self.mock_os_path.realpath.assert_called_once_with(
            '/dev/disk/by-scsid/emc-vol-19ab00bee9314e0f-894b409a00000000/'
            'scini'
        )
