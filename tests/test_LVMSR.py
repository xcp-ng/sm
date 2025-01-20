from sm_typing import override

import copy
import os
import unittest
import unittest.mock as mock

import uuid

import cleanup
import LVMSR
import lvhdutil
import lvutil
import vhdutil
from vditype import VdiType

import testlib

PV_FOR_VG_DATA = "/dev/mapper/3600a098038314650465d523777417142"


class SMLog(object):
    def __call__(self, *args):
        print(args)


class Stubs(object):
    def init_stubs(self):
        self._stubs = []

    def stubout(self, *args, **kwargs):
        patcher = mock.patch( * args, ** kwargs)
        self._stubs.append(patcher)
        return patcher.start()

    def remove_stubs(self):
        for patcher in self._stubs:
            patcher.stop()


class TestLVMSR(unittest.TestCase, Stubs):
    @override
    def setUp(self) -> None:
        self.init_stubs()

    @override
    def tearDown(self) -> None:
        self.remove_stubs()

    def create_LVMSR(self, master=False, command='foo', sr_uuid=None):
        srcmd = mock.Mock()
        srcmd.dconf = {'device': '/dev/bar'}
        if master:
            srcmd.dconf.update({"SRmaster": "true"})
        srcmd.params = {
            'command': command,
            'session_ref': 'some session ref',
            'sr_ref': 'test_sr_ref'}
        if sr_uuid is None:
            sr_uuid = str(uuid.uuid4())
        return LVMSR.LVMSR(srcmd, sr_uuid)

    @mock.patch('lvutil.Fairlock', autospec=True)
    @mock.patch('lvhdutil.getVDIInfo', autospec=True)
    @mock.patch('LVMSR.lock.Lock', autospec=True)
    @mock.patch('SR.XenAPI')
    def test_loadvids(self, mock_xenapi, mock_lock, mock_getVDIInfo, mock_lvlock):
        """sr.allVDIs populated by _loadvdis"""

        vdi_uuid = 'some VDI UUID'
        mock_getVDIInfo.return_value = {vdi_uuid: lvhdutil.VDIInfo(vdi_uuid)}
        sr = self.create_LVMSR()

        sr._loadvdis()

        self.assertEqual([vdi_uuid], list(sr.allVDIs.keys()))

    @mock.patch('lvhdutil.lvRefreshOnAllSlaves', autospec=True)
    @mock.patch('lvhdutil.getVDIInfo', autospec=True)
    @mock.patch('journaler.Journaler.getAll', autospec=True)
    @mock.patch('LVMSR.lock.Lock', autospec=True)
    @mock.patch('SR.XenAPI')
    def test_undoAllInflateJournals(
            self,
            mock_xenapi,
            mock_lock,
            mock_getAll,
            mock_getVDIInfo,
            mock_lvhdutil_lvRefreshOnAllSlaves):
        """No LV refresh on slaves when Cleaning up local LVHD SR's journal"""

        self.stubout('journaler.Journaler.remove')
        self.stubout('util.zeroOut')
        self.stubout('lvhdutil.deflate')
        self.stubout('util.SMlog', new_callable=SMLog)
        self.stubout('lvmcache.LVMCache')

        vdi_uuid = 'some VDI UUID'

        mock_getAll.return_value = {vdi_uuid: '0'}
        mock_getVDIInfo.return_value = {vdi_uuid: lvhdutil.VDIInfo(vdi_uuid)}

        sr = self.create_LVMSR()

        sr._undoAllInflateJournals()
        self.assertEqual(0, mock_lvhdutil_lvRefreshOnAllSlaves.call_count)

    @mock.patch('LVMSR.cleanup', autospec=True)
    @mock.patch('LVMSR.IPCFlag', autospec=True)
    @mock.patch('LVMSR.lock.Lock', autospec=True)
    @mock.patch('SR.XenAPI')
    @testlib.with_context
    def test_srlifecycle_success(self,
                            context,
                            mock_xenapi,
                            mock_lock,
                            mock_ipc,
                            mock_cleanup):
        sr_uuid = str(uuid.uuid4())
        self.stubout('lvutil._checkVG')
        mock_lvm_cache = self.stubout('lvmcache.LVMCache')
        mock_get_vg_stats = self.stubout('lvutil._getVGstats')
        mock_scsi_get_size = self.stubout('scsiutil.getsize')

        device_size = 100 * 1024 * 1024
        device_free = 10 * 1024 * 1024
        mock_get_vg_stats.return_value = {
            'physical_size': device_size,
            'physical_utilisation': device_free}
        mock_scsi_get_size.return_value = device_size
        mock_lvm_cache.return_value.checkLV.return_value = False

        mock_session = mock_xenapi.xapi_local.return_value
        mock_session.xenapi.SR.get_sm_config.return_value = {
            'allocation': 'thick',
            'use_vhd': 'true'
        }
        vdi_data = {
            'vdi1_ref': {
                'uuid': str(uuid.uuid4()),
                'name_label': "VDI1",
                'name_description': "First VDI",
                'is_a_snapshot': False,
                'snapshot_of': None,
                'snapshot_time': None,
                'type': 'User',
                'metadata-of-pool': None,
                'sm-config': {
                    'vdi_type': 'vhd'
                }
            },
            'vdi2_ref': {
                'uuid': str(uuid.uuid4()),
                'name_label': "VDI2",
                'name_description': "Second VDI",
                'is_a_snapshot': False,
                'snapshot_of': None,
                'snapshot_time': None,
                'type': 'User',
                'metadata-of-pool': None,
                'sm-config': {
                    'vdi_type': 'vhd'
                }
            }
        }
        mock_session.xenapi.SR.get_VDIs.return_value = list(vdi_data.keys())

        def get_vdi_data(vdi_key, vdi_ref):
            return vdi_data[vdi_ref][vdi_key]

        def get_vdi_by_uuid(vdi_uuid):
            return [v for v in vdi_data if v['uuid'] == vdi_uuid][0]

        mock_session.xenapi.VDI.get_uuid.side_effect = (
            lambda x: get_vdi_data('uuid', x))
        mock_session.xenapi.VDI.get_name_label.side_effect = (
            lambda x: get_vdi_data('name_label', x))
        mock_session.xenapi.VDI.get_name_description.side_effect = (
            lambda x: get_vdi_data('name_description', x))
        mock_session.xenapi.VDI.get_is_a_snapshot.side_effect = (
            lambda x: get_vdi_data('is_a_snapshot', x))
        mock_session.xenapi.VDI.get_snapshot_of.side_effect = (
            lambda x: get_vdi_data('snapshot_of', x))
        mock_session.xenapi.VDI.get_snapshot_time.side_effect = (
            lambda x: get_vdi_data('snapshot_time', x))
        mock_session.xenapi.VDI.get_type.side_effect = (
            lambda x: get_vdi_data('type', x))
        mock_session.xenapi.VDI.get_metadata_of_pool.side_effect = (
            lambda x: get_vdi_data('metadata-of-pool', x))
        mock_session.xenapi.VDI.get_sm_config.side_effect = (
            lambda x: get_vdi_data('sm-config', x))
        mock_session.xenapi.VDI.get_by_uuid.side_effect = get_vdi_by_uuid

        sr = self.create_LVMSR(master=True, command='sr_attach',
                                sr_uuid=sr_uuid)
        os.makedirs(sr.path)

        # Act (1)
        # This introduces the metadata volume
        sr.attach(sr.uuid)

        # Arrange (2)
        sr = self.create_LVMSR(master=True, command='sr_detach',
                                sr_uuid=sr_uuid)

        # Arrange for detach
        self.stubout('LVMSR.Fairlock')
        mock_remove_device = self.stubout(
            'LVMSR.lvutil.removeDevMapperEntry')
        mock_glob = self.stubout('glob.glob')
        mock_vdi_uuid = "72101dbd-bd62-4a14-a03c-afca8cceec86"
        mock_filepath = os.path.join(
            '/dev/mapper/', 'VG_XenStorage'
            f'--{sr_uuid.replace("-", "--")}-'
            f'{mock_vdi_uuid.replace("-", "--")}')
        mock_glob.return_value = [mock_filepath]
        mock_open_handles = self.stubout(
            'LVMSR.util.doesFileHaveOpenHandles')

        # Act (Detach)
        with self.assertRaises(Exception):
            # Fail the first one with busy handles
            mock_open_handles.return_value = True
            sr.detach(sr.uuid)

        # Now succeed
        mock_open_handles.return_value = False
        sr.detach(sr.uuid)

        # Assert for detach
        mock_remove_device.assert_called_once_with(mock_filepath, False)

        # Create new SR
        mock_lvm_cache.return_value.checkLV.return_value = True
        sr = self.create_LVMSR(master=True, command='sr_attach',
                                sr_uuid=sr_uuid)

        # Act (2)
        # This syncs the already existing metadata volume
        print("Doing second attach")
        sr.attach(sr.uuid)

        # Now resize
        mock_cmd_lvm = self.stubout('lvutil.cmd_lvm')
        lvm_cmds = {
            "pvs": PV_FOR_VG_DATA,
            "pvresize": ""
        }
        def cmd(args):
            return lvm_cmds[args[0]]

        mock_cmd_lvm.side_effect = cmd
        mock_scsi_get_size.return_value = device_size + (2 * 1024 * 1024 * 1024)
        sr.scan(sr.uuid)

        # Find new VDI during scan
        extended_vdi_data = copy.deepcopy(vdi_data)
        extended_vdi_data.update({
            'vdi3_ref': {
                'uuid': str(uuid.uuid4()),
                'name_label': "VDI3",
                'name_description': "Third  VDI",
                'is_a_snapshot': False,
                'snapshot_of': None,
                'snapshot_time': None,
                'type': 'User',
                'metadata-of-pool': None,
                'sm-config': {
                    'vdi_type': 'vhd'
                }
            }})
        with mock.patch('LVMSR.LVMMetadataHandler', autospec=True) as m, \
             mock.patch('LVMSR.vhdutil', autotspec=True) as v:
            m.return_value.getMetadata.return_value = [
                None, self.convert_vdi_to_meta(extended_vdi_data)]
            v._getVHDParentNoCheck.return_value = None
            sr.scan(sr.uuid)

            lvm_cache = mock_lvm_cache.return_value
            self.assertEqual(1, lvm_cache.activate.call_count)
            self.assertEqual(1, lvm_cache.deactivate.call_count)

        # Act (3)
        # This tests SR metadata updates
        sr.updateSRMetadata('thick')

        # Test that removing vdi_type on a vdi does crash properly
        del vdi_data['vdi2_ref']['sm-config']['vdi_type']
        with self.assertRaises(Exception):
            # Fail on vdi2_ref
            sr.updateSRMetadata('thick')

    def convert_vdi_to_meta(self, vdi_data):
        metadata = {}
        for item in vdi_data.items():
            metadata[item[0]] = {
                'uuid': item[1]['uuid'],
                'is_a_snapshot': item[1]['is_a_snapshot'],
                'snapshot_of': item[1]['snapshot_of'],
                'vdi_type': item[1]['sm-config']['vdi_type'],
                'name_label': item[1]['name_label'],
                'name_description': item[1]['name_description'],
                'type': item[1]['type'],
                'read_only': False,
                'managed': True,
            }
        return metadata


    def _setup_scan_sr(self, sr_uuid, mock_xenapi, mock_lvm_cache,
                        mock_get_vg_stats, mock_scsi_get_size,
                        xapi_vdi_uuids):
        device_size = 100 * 1024 * 1024
        mock_get_vg_stats.return_value = {
            'physical_size': device_size,
            'physical_utilisation': 10 * 1024 * 1024}
        mock_scsi_get_size.return_value = device_size

        mock_session = mock_xenapi.xapi_local.return_value
        mock_session.xenapi.SR.get_sm_config.return_value = {
            'allocation': 'thick',
            'use_vhd': 'true'
        }

        vdi_refs = ['vdi_ref_%s' % u for u in xapi_vdi_uuids]
        mock_session.xenapi.SR.get_VDIs.return_value = vdi_refs
        uuid_map = {ref: u for ref, u in zip(vdi_refs, xapi_vdi_uuids)}
        mock_session.xenapi.VDI.get_uuid.side_effect = uuid_map.get

        sr = self.create_LVMSR(master=True, command='sr_scan',
                                sr_uuid=sr_uuid)
        sr.mdexists = True
        return sr, mock_session

    @mock.patch('LVMSR.cleanup', autospec=True)
    @mock.patch('LVMSR.IPCFlag', autospec=True)
    @mock.patch('LVMSR.lock.Lock', autospec=True)
    @mock.patch('LVMSR.SR.XenAPI')
    @testlib.with_context
    def test_scan_stale_metadata_lv_missing_removes_from_metadata(
            self,
            context,
            mock_xenapi,
            mock_lock,
            mock_ipc,
            mock_cleanup):
        sr_uuid = str(uuid.uuid4())
        self.stubout('LVMSR.lvutil._checkVG')
        mock_lvm_cache = self.stubout('LVMSR.lvmcache.LVMCache')
        mock_get_vg_stats = self.stubout('LVMSR.lvutil._getVGstats')
        mock_scsi_get_size = self.stubout('LVMSR.scsiutil.getsize')
        self.stubout('LVMSR.lvutil.cmd_lvm')
        mock_cleanup.SR.TMP_RENAME_PREFIX = cleanup.SR.TMP_RENAME_PREFIX

        stale_vdi_uuid = str(uuid.uuid4())
        xapi_vdi_uuids = []

        sr, mock_session = self._setup_scan_sr(
            sr_uuid, mock_xenapi, mock_lvm_cache,
            mock_get_vg_stats, mock_scsi_get_size, xapi_vdi_uuids)

        mock_lvm_cache.return_value.checkLV.return_value = None

        stale_meta = {
            'vdi_key_0': {
                'uuid': stale_vdi_uuid,
                'is_a_snapshot': 0,
                'snapshot_of': '',
                'vdi_type': VdiType.VHD,
                'name_label': 'StaleVDI',
                'name_description': 'stale',
                'type': 'User',
                'read_only': False,
                'managed': True,
            }
        }

        with mock.patch('LVMSR.LVMMetadataHandler',
                        autospec=True) as mock_meta, \
             mock.patch('LVMSR.lvhdutil.getVDIInfo',
                        return_value={}), \
             mock.patch('LVMSR.lvutil._getVGstats',
                        return_value={'physical_size': 100 * 1024 * 1024,
                                      'physical_utilisation': 0}):
            mock_meta.return_value.getMetadata.return_value = [
                None, stale_meta]
            sr.scan(sr_uuid)

            mock_meta.return_value.deleteVdiFromMetadata.assert_called_once_with(
                stale_vdi_uuid)
            mock_session.xenapi.VDI.db_introduce.assert_not_called()

    @mock.patch('LVMSR.cleanup', autospec=True)
    @mock.patch('LVMSR.IPCFlag', autospec=True)
    @mock.patch('LVMSR.lock.Lock', autospec=True)
    @mock.patch('LVMSR.SR.XenAPI')
    @testlib.with_context
    def test_scan_metadata_vdi_not_in_xapi_lv_exists(
            self,
            context,
            mock_xenapi,
            mock_lock,
            mock_ipc,
            mock_cleanup):
        sr_uuid = str(uuid.uuid4())
        self.stubout('LVMSR.lvutil._checkVG')
        mock_lvm_cache = self.stubout('LVMSR.lvmcache.LVMCache')
        mock_get_vg_stats = self.stubout('LVMSR.lvutil._getVGstats')
        mock_scsi_get_size = self.stubout('LVMSR.scsiutil.getsize')
        self.stubout('LVMSR.lvutil.cmd_lvm')
        mock_cleanup.SR.TMP_RENAME_PREFIX = cleanup.SR.TMP_RENAME_PREFIX

        new_vdi_uuid = str(uuid.uuid4())
        xapi_vdi_uuids = []

        sr, mock_session = self._setup_scan_sr(
            sr_uuid, mock_xenapi, mock_lvm_cache,
            mock_get_vg_stats, mock_scsi_get_size, xapi_vdi_uuids)

        mock_lvm_cache.return_value.checkLV.return_value = True
        mock_lvm_cache.return_value.getSize.return_value = 10240
        mock_session.xenapi.VDI.db_introduce.return_value = 'new_vdi_ref'

        new_vdi_meta = {
            'vdi_key_0': {
                'uuid': new_vdi_uuid,
                'is_a_snapshot': 0,
                'snapshot_of': '',
                'vdi_type': VdiType.RAW,
                'name_label': 'NewVDI',
                'name_description': 'new',
                'type': 'User',
                'read_only': False,
                'managed': True,
            }
        }

        with mock.patch('LVMSR.LVMMetadataHandler',
                        autospec=True) as mock_meta, \
             mock.patch('LVMSR.lvhdutil.getVDIInfo',
                        return_value={}), \
             mock.patch('LVMSR.lvutil._getVGstats',
                        return_value={'physical_size': 100 * 1024 * 1024,
                                      'physical_utilisation': 0}):
            mock_meta.return_value.getMetadata.return_value = [
                None, new_vdi_meta]
            sr.scan(sr_uuid)

            mock_meta.return_value.deleteVdiFromMetadata.assert_not_called()
            mock_session.xenapi.VDI.db_introduce.assert_called_once()
            call_args = mock_session.xenapi.VDI.db_introduce.call_args
            self.assertEqual(call_args[0][0], new_vdi_uuid)


class TestLVMVDI(unittest.TestCase, Stubs):
    @override
    def setUp(self) -> None:
        self.init_stubs()

        lvhdutil_patcher = mock.patch('LVMSR.lvhdutil', autospec=True)
        self.mock_lvhdutil = lvhdutil_patcher.start()
        self.mock_lvhdutil.VG_LOCATION = lvhdutil.VG_LOCATION
        self.mock_lvhdutil.VG_PREFIX = lvhdutil.VG_PREFIX
        self.mock_lvhdutil.LV_PREFIX = lvhdutil.LV_PREFIX
        vhdutil_patcher = mock.patch('LVMSR.vhdutil', autospec=True)
        self.mock_vhdutil = vhdutil_patcher.start()
        self.mock_vhdutil.MAX_CHAIN_SIZE = vhdutil.MAX_CHAIN_SIZE
        lvutil_patcher = mock.patch('LVMSR.lvutil', autospec=True)
        self.mock_lvutil = lvutil_patcher.start()
        vdi_util_patcher = mock.patch('VDI.util', autospec=True)
        self.mock_vdi_util = vdi_util_patcher.start()
        sr_util_patcher = mock.patch('LVMSR.util', autospec=True)
        self.mock_sr_util = sr_util_patcher.start()
        self.mock_sr_util.gen_uuid.side_effect = str(uuid.uuid4())
        xmlrpclib_patcher = mock.patch('VDI.xmlrpc.client', autospec=True)
        self.mock_xmlrpclib = xmlrpclib_patcher.start()
        cbtutil_patcher = mock.patch('VDI.cbtutil', autospec=True)
        self.mock_cbtutil = cbtutil_patcher.start()
        doexec_patcher = mock.patch('util.doexec', autospec=True)
        self.mock_doexec = doexec_patcher.start()

        self.stubout('lvmcache.LVMCache')
        self.stubout('LVMSR.LVMSR._ensureSpaceAvailable')
        self.stubout('journaler.Journaler.create')
        self.stubout('journaler.Journaler.remove')
        self.stubout('LVMSR.RefCounter.set')
        self.stubout('LVMSR.RefCounter.put')
        self.stubout('LVMSR.LVMMetadataHandler')

        self.addCleanup(mock.patch.stopall)

    @override
    def tearDown(self) -> None:
        self.remove_stubs()

    def create_LVMSR(self):
        srcmd = mock.Mock()
        srcmd.dconf = {'device': '/dev/bar'}
        srcmd.params = {'command': 'foo', 'session_ref': 'some session ref'}
        return LVMSR.LVMSR(srcmd, "some SR UUID")

    def get_dummy_vdi(self, vdi_uuid):
        self.mock_lvhdutil.getVDIInfo.return_value = {
            vdi_uuid: lvhdutil.VDIInfo(vdi_uuid)}

        mock_lv =  lvutil.LVInfo('test-lv')
        mock_lv.size = 10240
        mock_lv.active = True
        mock_lv.hidden = False
        mock_lv.vdiType = VdiType.VHD

        self.mock_lvhdutil.getLVInfo.return_value = {
            vdi_uuid: mock_lv}

        return mock_lv

    def get_dummy_vhd(self, vdi_uuid, hidden):
        test_vhdInfo = vhdutil.VHDInfo(vdi_uuid)
        test_vhdInfo.hidden = hidden
        self.mock_vhdutil.getVHDInfo.return_value = test_vhdInfo

    @mock.patch('LVMSR.lock.Lock', autospec=True)
    @mock.patch('SR.XenAPI')
    def test_clone_success(self, mock_xenapi, mock_lock):
        """
        Successfully create clone
        """

        # Arrange
        xapi_session = mock_xenapi.xapi_local.return_value
        xapi_session.xenapi.VDI.get_sm_config.return_value = {}
        vdi_uuid = 'some VDI UUID'
        mock_lv = self.get_dummy_vdi(vdi_uuid)
        self.get_dummy_vhd(vdi_uuid, False)

        sr = self.create_LVMSR()
        sr.isMaster = True
        sr.legacyMode = False
        sr.srcmd.params = {'vdi_ref': 'test ref'}

        vdi = sr.vdi('some VDI UUID')
        self.mock_sr_util.pathexists.return_value = True

        self.mock_vhdutil.getDepth.return_value = 1

        # Act
        clone = vdi.clone(sr.uuid, 'some VDI UUID')

        # Assert
        self.assertIsNotNone(clone)

    @mock.patch('LVMSR.lock.Lock', autospec=True)
    @mock.patch('SR.XenAPI')
    def test_snapshot_attached_success(self, mock_xenapi, mock_lock):
        """
        LVMSR.snapshot, attached on host, no CBT
        """
        # Arrange
        xapi_session = mock_xenapi.xapi_local.return_value
        xapi_session.xenapi.VDI.get_sm_config.return_value = {}

        vdi_uuid = 'some VDI UUID'
        mock_lv = self.get_dummy_vdi(vdi_uuid)
        self.get_dummy_vhd(vdi_uuid, False)

        sr = self.create_LVMSR()
        sr.isMaster = True
        sr.legacyMode = False
        sr.srcmd.params = {
            'vdi_ref': 'test ref',
            'driver_params': {
                'type': 'double'}
            }
        sr.cmd = "vdi_snapshot"

        vdi = sr.vdi('some VDI UUID')
        vdi.vdi_type = VdiType.VHD
        self.mock_sr_util.pathexists.return_value = True
        self.mock_sr_util.get_hosts_attached_on.return_value = ["hostref2"]
        self.mock_sr_util.get_this_host_ref.return_value = ["hostref1"]
        self.mock_vhdutil.getDepth.return_value = 1

        # Act
        snap = vdi.snapshot(sr.uuid, "Dummy UUID")

        # Assert
        self.assertIsNotNone(snap)

    @mock.patch('LVMSR.lock.Lock', autospec=True)
    @mock.patch('SR.XenAPI')
    def test_snapshot_attached_cbt_success(self, mock_xenapi, mock_lock):
        """
        LVMSR.snapshot, attached on host, with CBT
        """
        # Arrange
        xapi_session = mock_xenapi.xapi_local.return_value
        xapi_session.xenapi.VDI.get_sm_config.return_value = {}

        vdi_uuid = 'some VDI UUID'
        mock_lv = self.get_dummy_vdi(vdi_uuid)
        self.get_dummy_vhd(vdi_uuid, False)

        sr = self.create_LVMSR()
        sr.isMaster = True
        sr.legacyMode = False
        sr.srcmd.params = {
            'vdi_ref': 'test ref',
            'driver_params': {
                'type': 'double'}
            }
        sr.cmd = "vdi_snapshot"

        vdi = sr.vdi('some VDI UUID')
        vdi.vdi_type = VdiType.VHD
        self.mock_sr_util.pathexists.return_value = True
        self.mock_sr_util.get_hosts_attached_on.return_value = ["hostref2"]
        self.mock_sr_util.get_this_host_ref.return_value = ["hostref1"]
        self.mock_vdi_util.sr_get_capability.return_value = {
            'VDI_CONFIG_CBT'}
        self.mock_vhdutil.getDepth.return_value = 1

        # Act
        with mock.patch('lock.Lock'):
            snap = vdi.snapshot(sr.uuid, "Dummy UUID")

        # Assert
        self.assertIsNotNone(snap)
        self.assertEqual(self.mock_cbtutil.set_cbt_child.call_count, 3)

    @mock.patch('LVMSR.lock.Lock', autospec=True)
    @mock.patch('SR.XenAPI')
    def test_update_slaves_on_cbt_disable(self, mock_xenapi, mock_lock):
        """
        Ensure we tell the supporter host when we disable CBT for one of its VMs
        """
        # Arrange
        xapi_session = mock_xenapi.xapi_local.return_value

        vdi_uuid = str(uuid.uuid4)
        mock_lv = self.get_dummy_vdi(vdi_uuid)
        self.get_dummy_vhd(vdi_uuid, False)

        sr = self.create_LVMSR()
        sr.isMaster = True

        vdi = sr.vdi(vdi_uuid)
        vdi.vdi_type = VdiType.VHD

        self.mock_sr_util.get_this_host_ref.return_value = 'ref1'
        self.mock_sr_util.get_hosts_attached_on.return_value = ['ref2']

        # Act
        log_file_path = "test_log_path"
        vdi.update_slaves_on_cbt_disable(log_file_path)

        # Assert
        self.assertEqual(1, xapi_session.xenapi.host.call_plugin.call_count)
        xapi_session.xenapi.host.call_plugin.assert_has_calls([
            mock.call('ref2', 'on-slave', 'multi', mock.ANY)
        ])

    @mock.patch('LVMSR.lock.Lock', autospec=True)
    @mock.patch('SR.XenAPI')
    def test_snapshot_secondary_success(self, mock_xenapi, mock_lock):
        """
        LVMSR.snapshot, attached on host with secondary mirror
        """
        # Arrange
        xapi_session = mock_xenapi.xapi_local.return_value
        xapi_session.xenapi.VDI.get_sm_config.return_value = {}

        vdi_ref = mock.MagicMock()
        xapi_session.xenapi.VDI.get_by_uuid.return_value = vdi_ref
        vdi_uuid = 'some VDI UUID'
        self.get_dummy_vdi(vdi_uuid)
        self.get_dummy_vhd(vdi_uuid, False)

        sr = self.create_LVMSR()
        sr.isMaster = True
        sr.legacyMode = False
        sr.srcmd.params = {
            'vdi_ref': 'test ref',
            'driver_params': {
                'type': 'double',
                'mirror': 'nbd:mirror_vbd/5/xvda'}
            }
        sr.cmd = "vdi_snapshot"

        vdi = sr.vdi('some VDI UUID')
        vdi.vdi_type = VdiType.VHD
        self.mock_sr_util.pathexists.return_value = True
        self.mock_sr_util.get_hosts_attached_on.return_value = ["hostref2"]
        self.mock_sr_util.get_this_host_ref.return_value = ["hostref1"]
        self.mock_vhdutil.getDepth.return_value = 1

        # Act
        with mock.patch('lock.Lock'):
            snap = vdi.snapshot(sr.uuid, "Dummy UUID")

        # Assert
        self.assertIsNotNone(snap)
        xapi_session.xenapi.VDI.add_to_other_config.assert_called_once_with(
            vdi_ref, cleanup.VDI.DB_LEAFCLSC, cleanup.VDI.LEAFCLSC_DISABLED)
