from sm_typing import override

import unittest
import unittest.mock as mock
import SR
from SR import deviceCheck
import xs_errors


class TestSR(unittest.TestCase):

    class deviceTest(object):

        def __init__(self, device=None):
            self.dconf = {}
            if device:
                self.dconf['device'] = device

        @deviceCheck
        def verify(self):
            pass

    @override
    def setUp(self) -> None:
        pass

    @override
    def tearDown(self) -> None:
        pass

    def create_SR(self, cmd, dconf, cmd_params=None):
        srcmd = mock.Mock()
        srcmd.dconf = dconf
        srcmd.params = {'command': cmd}
        if cmd_params:
            srcmd.params.update(cmd_params)
        return SR.SR(srcmd, "some SR UUID")

    def test_device_check_success(self):
        """
        Test the device check decorator with a device configured
        """
        checker = TestSR.deviceTest(device="/dev/sda")

        checker.verify()

    def test_device_check_nodevice(self):
        """
        Test the device check decorator with no device configured
        """
        checker = TestSR.deviceTest()

        with self.assertRaises(xs_errors.SROSError):
            checker.verify()

    @mock.patch('SR.SR.scan', autospec=True)
    def test_after_master_attach_success(self, mock_scan):
        """
        Test that after_master_attach calls scan
        """
        sr1 = self.create_SR("sr_create", {'ISCSIid': '12333423'})

        sr1.after_master_attach('dummy uuid')

        mock_scan.assert_called_once_with(sr1, 'dummy uuid')

    @mock.patch('SR.XenAPI')
    @mock.patch('SR.SR.scan', autospec=True)
    @mock.patch('SR.util.SMlog', autospec=True)
    def test_after_master_attach_vdi_not_available(
            self, mock_log, mock_scan, mock_xenapi):
        """
        Test that after_master_attach calls scan
        """
        mock_session = mock.MagicMock(name='MockXapiSession')
        mock_xenapi.xapi_local.return_value = mock_session
        sr1 = self.create_SR("sr_create", {'ISCSIid': '12333423'},
            {'session_ref': 'session1'})

        mock_scan.side_effect = xs_errors.SROSError(
            46, "The VDI is not available")

        sr1.after_master_attach('dummy uuid')

        mock_scan.assert_called_once_with(sr1, 'dummy uuid')

        self.assertEqual(1, mock_log.call_count)
        self.assertIn("Error in SR.after_master_attach",
                      mock_log.call_args[0][0])
        mock_session.xenapi.message.create.assert_called_once_with(
            "POST_ATTACH_SCAN_FAILED", 2, 'SR', 'dummy uuid', mock.ANY)

    def test_synchronise_gone_marks_missing(self):
        sr = mock.MagicMock()
        session = sr.session
        vdi_ref = 'OpaqueRef:vdi'
        session.xenapi.VDI.get_by_uuid.return_value = vdi_ref

        record = mock.Mock()
        record.sr = sr
        record.gone = {'gone-location'}
        record.get_xenapi_vdi.return_value = {
            'location': 'gone-location',
            'uuid': 'vdi-uuid',
            'managed': True,
        }

        SR.ScanRecord.synchronise_gone(record)

        session.xenapi.VDI.set_missing.assert_called_once_with(vdi_ref, True)
        sr.forget_vdi.assert_not_called()

    def test_synchronise_gone_forgets_unmanaged(self):
        # Hidden leaf base copy skipped by the scan while waiting for the GC
        sr = mock.MagicMock()
        session = sr.session

        record = mock.Mock()
        record.sr = sr
        record.gone = {'base-copy-location'}
        record.get_xenapi_vdi.return_value = {
            'location': 'base-copy-location',
            'uuid': 'base-copy-uuid',
            'managed': False,
        }

        SR.ScanRecord.synchronise_gone(record)

        sr.forget_vdi.assert_called_once_with('base-copy-uuid')
        session.xenapi.VDI.set_missing.assert_not_called()

    def test_clear_missing_vdi_when_present(self):
        sr = mock.MagicMock()
        session = sr.session
        vdi_ref = 'OpaqueRef:vdi'
        session.xenapi.VDI.get_by_uuid.return_value = vdi_ref

        record = mock.Mock()
        record.sr = sr
        record.all_xenapi_locations.return_value = {'present-location'}
        record.get_sm_vdi.return_value = mock.Mock()
        record.get_xenapi_vdi.return_value = {
            'location': 'present-location',
            'uuid': 'vdi-uuid',
            'missing': True,
        }

        SR.ScanRecord._clear_missing_vdi(record)

        session.xenapi.VDI.set_missing.assert_called_once_with(vdi_ref, False)

    def test_clear_missing_vdi_skips_gone(self):
        sr = mock.MagicMock()
        session = sr.session

        record = mock.Mock()
        record.sr = sr
        record.all_xenapi_locations.return_value = {'gone-location'}
        record.get_sm_vdi.side_effect = KeyError('gone-location')

        SR.ScanRecord._clear_missing_vdi(record)

        session.xenapi.VDI.set_missing.assert_not_called()
