#!/usr/bin/python3
# SPDX-License-Identifier: LGPL-2.1-only
"""Experimental ephemeral ISO media served by an XO browser session.

A systemd-supervised nbdkit process owns each attached VDI's Unix socket.
No ISO bytes are persisted. Device configuration contains a short-lived bearer
URL: treat it as a secret and do not log it.
"""
import os
import socket
import shutil
import subprocess
import time
import uuid
import xmlrpc.client
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

import SR
import VDI
import blktap2
import util
from lock import Lock

DRIVER_INFO = {
    'name': 'Browser ISO',
    'description': 'Experimental read-only browser media over HTTPS and NBD',
    'vendor': 'Vates', 'copyright': '(C) 2026 Vates',
    'driver_version': '0.1', 'required_api_version': '1.0',
    'capabilities': ['SR_ATTACH', 'SR_DETACH', 'SR_SCAN', 'VDI_CREATE',
                     'VDI_DELETE', 'VDI_ATTACH', 'VDI_DETACH'],
    'configuration': [['url', 'HTTPS media capability URL'], ['size', 'ISO size in bytes']],
}
RUNTIME = '/run/sm-browseriso'


def validate_config(config):
    url = urlsplit(config.get('url', ''))
    schemes = ('https', 'http') if config.get('allow_http') == 'true' else ('https',)
    if (url.scheme not in schemes or not url.hostname or url.username or
            url.password or url.fragment or url.query or
            not url.path.startswith('/api/browser-media/')):
        raise util.SMException('Browser ISO requires an XO HTTPS media URL')
    size = int(config.get('size', '0'))
    if size < 32768 or size > 128 * 1024 ** 3 or size % 512:
        raise util.SMException('Invalid browser ISO size')
    return size


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_source(config):
    """PBD plug validates that this host can read the same medium as its peers."""
    try:
        request = Request(config['url'], method='HEAD')
        with build_opener(NoRedirect).open(request, timeout=10) as response:
            if (response.status != 200 or
                    int(response.headers.get('Content-Length', '-1')) != validate_config(config) or
                    response.headers.get('Accept-Ranges') != 'bytes'):
                raise ValueError('Unexpected media metadata')
    except Exception:
        # urllib exceptions include the bearer URL. Never expose them in SM logs.
        raise util.SMException('Browser ISO endpoint unreachable or metadata mismatch') from None


class BrowserISOSR(SR.SR):
    direct_nbd = True

    @staticmethod
    def handles(sr_type):
        return sr_type == 'browseriso'

    def load(self, sr_uuid):
        self.sr_vditype = 'iso'
        self.lock = Lock('sr', sr_uuid)
        self.ops_exclusive = ['sr_scan', 'vdi_create', 'vdi_delete', 'vdi_attach', 'vdi_detach']
        self.media_size = validate_config(self.dconf)

    def create(self, sr_uuid, size):
        self.attach(sr_uuid)

    def attach(self, sr_uuid):
        if shutil.which('nbdkit') is None:
            raise util.SMException('Install nbdkit and its curl plugin on this host')
        result = subprocess.run([shutil.which('nbdkit'), 'curl', '--dump-plugin'],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if result.returncode:
            raise util.SMException('The nbdkit curl plugin is unavailable')
        check_source(self.dconf)

    def detach(self, sr_uuid):
        pass

    def delete(self, sr_uuid):
        pass

    def scan(self, sr_uuid):
        # Metadata is authoritative; never remove an attached VDI merely because
        # its browser is temporarily unavailable.
        self.physical_size = self.media_size
        self.physical_utilisation = 0
        self.virtual_allocation = 0
        for ref, record in util.list_VDI_records_in_sr(self).items():
            vdi = self.vdi(record['uuid'])
            vdi.label = record['name_label']
            self.vdis[vdi.uuid] = vdi
        return super(BrowserISOSR, self).scan(sr_uuid)

    def vdi(self, vdi_uuid):
        return BrowserISOVDI(self, vdi_uuid)


class BrowserISOVDI(VDI.VDI):
    def load(self, vdi_uuid):
        self.uuid = str(uuid.UUID(vdi_uuid))
        self.location = self.uuid
        self.vdi_type = 'iso'
        self.read_only = True
        self.size = self.sr.media_size
        self.utilisation = 0
        self.sm_config = {}
        self.socket_path = os.path.join(RUNTIME, self.uuid + '.sock')
        self.unit = 'sm-browseriso-' + self.uuid + '.service'

    def create(self, sr_uuid, vdi_uuid, size):
        if size != self.size or not self.read_only:
            raise util.SMException('Browser media must be read-only and match its source size')
        self._db_introduce()
        return self.get_params()

    def delete(self, sr_uuid, vdi_uuid):
        self.detach(sr_uuid, vdi_uuid)
        self._db_forget()

    def _ready(self):
        # Connecting then closing before negotiation is harmless to nbdkit.
        with socket.socket(socket.AF_UNIX) as sock:
            sock.settimeout(0.5)
            try:
                sock.connect(self.socket_path)
                return True
            except OSError:
                return False

    def attach(self, sr_uuid, vdi_uuid, writable=False):
        if writable:
            raise util.SMException('Browser media is read-only')
        if not self._ready():
            os.makedirs(RUNTIME, mode=0o700, exist_ok=True)
            self.detach(sr_uuid, vdi_uuid)
            # No shell interpolation. The URL is a capability; avoid logging this
            # argv or subprocess output. systemd owns process lifetime, not SM.
            result = subprocess.run([
                '/usr/bin/systemd-run', '--quiet', '--unit=' + self.unit,
                shutil.which('nbdkit') or '/usr/bin/nbdkit', '-f', '-r', '-U', self.socket_path,
                # Tapdisk's NBD client uses the old-style handshake reliably;
                # QEMU connects to tapdisk's own new-style NBD endpoint.
                '--oldstyle', 'curl',
                'url=' + self.sr.dconf['url'],
                'protocols=' + urlsplit(self.sr.dconf['url']).scheme,
                'followlocation=false', 'timeout=35',
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode:
                raise util.SMException('Could not start browser ISO adapter')
            for _ in range(100):
                if self._ready():
                    break
                time.sleep(0.05)
            else:
                self.detach(sr_uuid, vdi_uuid)
                raise util.SMException('Browser ISO adapter did not become ready')
        try:
            tap = blktap2.Tapdisk.find_by_path(self.socket_path)
            if tap is None:
                tap = blktap2.Tapdisk.launch(self.socket_path, 'nbd', True)
        except Exception:
            self.detach(sr_uuid, vdi_uuid)
            raise
        # vbd3 discovers the tapdisk from this endpoint and connects the PV
        # ring. Both UEFI/PV readers and QEMU now use the same read-only backend.
        nbd_path = '/run/blktap-control/nbd%d.%d' % (int(tap.pid), int(tap.minor))
        return xmlrpc.client.dumps(({
            'params_nbd': 'nbd:unix:{}:exportname={}'.format(nbd_path, self.uuid),
            'xenstore_data': {}, 'o_direct': True,
        },), '', True)

    def detach(self, sr_uuid, vdi_uuid):
        tap = blktap2.Tapdisk.find_by_path(self.socket_path)
        if tap is not None:
            # Keep the source alive until outstanding tapdisk reads complete.
            tap.shutdown()
        stop = ['/usr/bin/systemctl', 'stop', self.unit]
        try:
            subprocess.run(stop, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5)
        except subprocess.TimeoutExpired:
            # Read-only, stateless adapter: an inherited QEMU socket can keep
            # nbdkit alive after eject. Bound teardown instead of waiting for
            # systemd's 90-second default stop timeout.
            subprocess.run(['/usr/bin/systemctl', 'kill', '--kill-who=all',
                            '--signal=KILL', self.unit],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=5)
            subprocess.run(stop, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=5)
        subprocess.run(['/usr/bin/systemctl', 'reset-failed', self.unit],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass


SR.registerSR(BrowserISOSR)


if __name__ == "__main__":
    import SRCommand
    SRCommand.run(BrowserISOSR, DRIVER_INFO)
