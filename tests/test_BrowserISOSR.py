import unittest
from unittest import mock
from types import SimpleNamespace
import xmlrpc.client
import subprocess

import testlib
from BrowserISOSR import BrowserISOVDI, validate_config, check_source
import util
import blktap2
from SRCommand import SRCommand

UUID = 'd92b0a98-b17c-4a83-8339-dbd66de6de67'
CONFIG = {'url': 'https://xo.example/api/browser-media/capability/iso', 'size': '32768'}


class TestBrowserISO(unittest.TestCase):
    def setUp(self):
        patch = mock.patch('BrowserISOSR.blktap2.Tapdisk')
        self.tapdisk = patch.start()
        self.addCleanup(patch.stop)
        self.tapdisk.find_by_path.return_value = None
        self.tap = self.tapdisk.launch.return_value
        self.tap.pid, self.tap.minor = 1234, 5

    def vdi(self):
        sr = SimpleNamespace(media_size=32768, session=mock.Mock(), dconf=CONFIG)
        return BrowserISOVDI(sr, UUID)

    def test_validate(self):
        self.assertEqual(validate_config(CONFIG), 32768)
        for url in ['file:///etc/passwd', 'http://xo/api/browser-media/x',
                    'https://user:pass@xo/api/browser-media/x', 'https://xo/unrelated']:
            with self.assertRaises(util.SMException):
                validate_config(dict(CONFIG, url=url))
        for size in ['0', '32769', str(129 * 1024 ** 3)]:
            with self.assertRaises(util.SMException):
                validate_config(dict(CONFIG, size=size))

    def test_http_requires_explicit_lab_opt_in(self):
        config = dict(CONFIG, url='http://xo/api/browser-media/test/iso')
        with self.assertRaises(util.SMException):
            validate_config(config)
        self.assertEqual(validate_config(dict(config, allow_http='true')), 32768)

    def test_no_writable_attach(self):
        with self.assertRaises(util.SMException):
            self.vdi().attach(UUID, UUID, True)

    def test_existing_socket_starts_readonly_pv_backend(self):
        vdi = self.vdi()
        with mock.patch.object(vdi, '_ready', return_value=True), mock.patch('subprocess.run') as run:
            result, _ = xmlrpc.client.loads(vdi.attach(UUID, UUID))
        self.assertNotIn('params', result[0])
        self.assertEqual(result[0]['params_nbd'], 'nbd:unix:/run/blktap-control/nbd1234.5:exportname=' + UUID)
        run.assert_not_called()
        self.tapdisk.launch.assert_called_once_with(vdi.socket_path, 'nbd', True)

    def test_reuses_existing_tapdisk(self):
        vdi = self.vdi()
        self.tapdisk.find_by_path.return_value = self.tap
        with mock.patch.object(vdi, '_ready', return_value=True):
            vdi.attach(UUID, UUID)
        self.tapdisk.launch.assert_not_called()

    def test_tapdisk_failure_rolls_back_adapter(self):
        vdi = self.vdi()
        self.tapdisk.launch.side_effect = RuntimeError('tapdisk failed')
        with mock.patch.object(vdi, '_ready', return_value=True), mock.patch.object(vdi, 'detach') as detach:
            with self.assertRaisesRegex(RuntimeError, 'tapdisk failed'):
                vdi.attach(UUID, UUID)
        detach.assert_called_once_with(UUID, UUID)

    def test_detach_stops_tapdisk_before_source(self):
        vdi = self.vdi()
        self.tapdisk.find_by_path.return_value = self.tap
        events = []
        self.tap.shutdown.side_effect = lambda: events.append('tapdisk')
        with mock.patch('subprocess.run', side_effect=lambda *a, **k: events.append('source')), mock.patch('os.unlink'):
            vdi.detach(UUID, UUID)
        self.assertEqual(events[0], 'tapdisk')
        self.assertIn('source', events)

    def test_start_failure(self):
        vdi = self.vdi()
        with mock.patch.object(vdi, '_ready', return_value=False), \
                mock.patch.object(vdi, 'detach'), mock.patch('os.makedirs'), \
                mock.patch('subprocess.run', return_value=SimpleNamespace(returncode=1)):
            with self.assertRaisesRegex(util.SMException, 'Could not start'):
                vdi.attach(UUID, UUID)

    def test_start_readonly(self):
        vdi = self.vdi()
        with mock.patch.object(vdi, '_ready', side_effect=[False, True]), \
                mock.patch.object(vdi, 'detach'), mock.patch('os.makedirs'), \
                mock.patch('subprocess.run', return_value=SimpleNamespace(returncode=0)) as run:
            vdi.attach(UUID, UUID)
        argv = run.call_args[0][0]
        self.assertIn('-r', argv)
        self.assertIn('--oldstyle', argv)
        self.assertIn('protocols=https', argv)
        self.assertIn('followlocation=false', argv)
        self.assertIn('url=' + CONFIG['url'], argv)

    def test_detach_bounds_adapter_shutdown(self):
        vdi = self.vdi()
        with mock.patch('os.unlink') as unlink, mock.patch('subprocess.run') as run:
            run.side_effect = [subprocess.TimeoutExpired('systemctl', 5),
                               mock.Mock(), mock.Mock(), mock.Mock()]
            vdi.detach(UUID, UUID)
        self.assertIn('--signal=KILL', run.call_args_list[1][0][0])
        unlink.assert_called_once_with(vdi.socket_path)

    def test_dispatch_bypasses_tapdisk(self):
        command = SRCommand({})
        command.cmd = 'vdi_attach'
        command.params = {'sr_uuid': UUID, 'args': ['false'], 'device_config': CONFIG}
        command.vdi_uuid = UUID
        sr = SimpleNamespace(direct_nbd=True, dconf={})
        target = mock.Mock()
        with mock.patch('SRCommand.blktap2.VDI') as tap, mock.patch('SRCommand.util.SMlog') as log:
            command._run(sr, target)
        tap.assert_not_called()
        target.attach.assert_called_once_with(UUID, UUID, False)
        self.assertNotIn('capability', str(log.call_args_list))
        self.assertEqual(command.params['device_config'], CONFIG)


class TestSourceProbe(unittest.TestCase):
    def test_probe_size_and_range_support(self):
        with mock.patch('BrowserISOSR.build_opener') as opener:
            response = opener.return_value.open.return_value.__enter__.return_value
            response.status = 200
            response.headers = {'Content-Length': '32768', 'Accept-Ranges': 'bytes'}
            check_source(CONFIG)
            response.headers['Content-Length'] = '65536'
            with self.assertRaisesRegex(util.SMException, 'metadata mismatch'):
                check_source(CONFIG)

    def test_probe_error_redacts_capability(self):
        with mock.patch('BrowserISOSR.build_opener') as opener:
            opener.return_value.open.side_effect = Exception(CONFIG['url'])
            with self.assertRaises(util.SMException) as context:
                check_source(CONFIG)
            self.assertNotIn('capability', str(context.exception))

class TestNbdTapdiskArgument(unittest.TestCase):
    def test_nbd_tapdisk_is_recognized_by_global_enumeration(self):
        arg = blktap2.Tapdisk.Arg.parse('nbd:/run/sm-browseriso/test.sock')
        self.assertEqual(arg.type, 'nbd')
        self.assertEqual(arg.path, '/run/sm-browseriso/test.sock')
