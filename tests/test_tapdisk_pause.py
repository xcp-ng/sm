from sm_typing import override

import unittest
import uuid
from unittest import mock

import blktap2
import tapdisk_pause


class TestTapdiskPause(unittest.TestCase):
    @override
    def setUp(self):
        self.mock_session = mock.MagicMock()
        log_patcher = mock.patch("tapdisk_pause.util.SMlog")
        self.mock_log = log_patcher.start()
        exists_patcher = mock.patch('tapdisk_pause.os.path.exists')
        self.mock_exists = exists_patcher.start()
        lock_patcher = mock.patch('tapdisk_pause.Lock')
        self.mock_lock = lock_patcher.start()
        self.mock_tapdisk = mock.create_autospec(blktap2.Tapdisk)
        blktap2_patcher = mock.patch('tapdisk_pause.blktap2')
        self.mock_blktap2 = blktap2_patcher.start()
        self.mock_blktap2.Tapdisk.major.return_value = 254
        vdi_patcher = mock.patch('tapdisk_pause.VDI')
        self.mock_vdi = vdi_patcher.start()
        self.mock_blktap2.Tapdisk.from_minor.side_effect = lambda x: self.mock_tapdisk
        readlink_patcher = mock.patch('tapdisk_pause.os.readlink')
        self.mock_readlink = readlink_patcher.start()
        self.mock_readlink.side_effect = lambda x: x
        get_dev_patcher = mock.patch('tapdisk_pause._getDevMajor_minor')
        self.mock_getdev = get_dev_patcher.start()
        self.addCleanup(mock.patch.stopall)

    def test_refresh_success(self):
        # Arrange
        vdi_uuid = str(uuid.uuid4())
        sr_uuid = str(uuid.uuid4())
        args = {
            'vdi_uuid': vdi_uuid,
            'sr_uuid': sr_uuid
        }

        self.mock_getdev.return_value = (254, 5)
        test_vdi = self.mock_vdi.VDI.from_uuid.return_value
        test_vdi._get_blocktracking_status.return_value = False
        self.mock_tapdisk.is_paused.return_value = False

        # Act
        tapdisk_pause.tapRefresh(self.mock_session, args)

        # Assert
        self.mock_tapdisk.pause.assert_called_once_with()
        self.mock_tapdisk.unpause.assert_called_once_with(
            None, None, None, None)

    def test_refresh_recover_from_failed(self):
        """
        If a previous refresh has failed after pausing the tapdisk, recover
        """
        # Arrange
        vdi_uuid = str(uuid.uuid4())
        sr_uuid = str(uuid.uuid4())
        args = {
            'vdi_uuid': vdi_uuid,
            'sr_uuid': sr_uuid
        }

        self.mock_getdev.return_value = (254, 5)
        test_vdi = self.mock_vdi.VDI.from_uuid.return_value
        test_vdi._get_blocktracking_status.return_value = False
        self.mock_tapdisk.is_paused.return_value = True
        test_sm_config = {}
        xapi_session = self.mock_session.xenapi
        xapi_session.VDI.get_sm_config.return_value = test_sm_config

        # Act
        tapdisk_pause.tapRefresh(self.mock_session, args)

        # Assert
        self.mock_tapdisk.pause.assert_not_called()
        self.mock_tapdisk.unpause.assert_called_once_with(
            None, None, None, None)
