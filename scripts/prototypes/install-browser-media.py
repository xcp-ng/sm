#!/usr/bin/env python3
"""Install the prototype on a flat-layout XCP-ng 8.3 SM (run as root).

Usage: python3 install-browser-media.py /path/to/BrowserISOSR.py
Requires the isolated nbdkit build documented in BROWSER_MEDIA_PROTOTYPE.md.
This patches two dispatcher hooks and the accepted tapdisk type list.
"""
import os
from pathlib import Path
import shutil
import sys

root = Path('/opt/xensource/sm')
backup = Path('/root/browser-media-prototype/backup')
nbdkit = '/opt/browser-media-prototype/nbdkit/sbin/nbdkit'
if os.geteuid() != 0 or not os.path.isfile(nbdkit):
    raise SystemExit('Run as root after installing the isolated nbdkit build')

source = Path(sys.argv[1]).read_text()
imports = 'from sm import SR, VDI, blktap2\nfrom sm.core import util\nfrom sm.core.lock import Lock'
if imports not in source and 'import blktap2' not in source:
    raise SystemExit('Unrecognized driver imports; refusing partial installation')
source = source.replace(imports, 'import SR\nimport VDI\nimport blktap2\nimport util\nfrom lock import Lock')
source = source.replace("shutil.which('nbdkit')", repr(nbdkit))
compile(source, 'BrowserISOSR.py', 'exec')

path = root / 'SRCommand.py'
dispatcher = path.read_text()
if 'if getattr(sr, "direct_nbd", False):' not in dispatcher:
    log_anchor = "            if 'session_ref' in params_to_log:\n"
    attach_anchor = "        if self.cmd == 'vdi_create':\n"
    if dispatcher.count(log_anchor) != 1 or dispatcher.count(attach_anchor) != 1:
        raise SystemExit('Unrecognized dispatcher; refusing to patch')
    dispatcher = dispatcher.replace(log_anchor, '''            if getattr(sr, 'direct_nbd', False):
                params_to_log = dict(params_to_log)
                params_to_log['device_config'] = '<redacted NBD configuration>'

'''+log_anchor)
    dispatcher = dispatcher.replace(attach_anchor, '''        # Browser-media prototype: backend owns its NBD server.
        if getattr(sr, "direct_nbd", False):
            if self.cmd == 'vdi_attach':
                return target.attach(self.params['sr_uuid'], self.vdi_uuid,
                                     self.params['args'][0] == 'true')
            if self.cmd == 'vdi_detach':
                return target.detach(self.params['sr_uuid'], self.vdi_uuid)

'''+attach_anchor)
compile(dispatcher, str(path), 'exec')
backup.mkdir(parents=True, exist_ok=True)
if not (backup / 'SRCommand.py').exists():
    shutil.copy2(str(path), str(backup / 'SRCommand.py'))

def install(path, content, mode):
    temporary = path.with_name(path.name + '.browser-media-new')
    temporary.write_text(content)
    temporary.chmod(mode)
    os.replace(str(temporary), str(path))

# Every SM process must recognize NBD tapdisks when enumerating tap-ctl output.
tap_path = root / 'blktap2.py'
tap_source = tap_path.read_text()
old_types = "TYPES = ['aio', 'vhd', 'qcow2']" if "TYPES = ['aio', 'vhd', 'qcow2']" in tap_source or "TYPES = ['aio', 'vhd', 'qcow2', 'nbd']" in tap_source else "TYPES = ['aio', 'vhd']"
new_types = old_types[:-1] + ", 'nbd']"
if old_types in tap_source:
    if not (backup / 'blktap2.py').exists():
        shutil.copy2(str(tap_path), str(backup / 'blktap2.py'))
    tap_source = tap_source.replace(old_types, new_types)
    compile(tap_source, str(tap_path), 'exec')
    install(tap_path, tap_source, tap_path.stat().st_mode & 0o777)
elif new_types not in tap_source:
    raise SystemExit('Unrecognized tapdisk type table; refusing installation')

install(root / 'BrowserISOSR.py', source, 0o644)
install(root / 'BrowserISOSR', '''#!/usr/bin/python3
import SRCommand
from BrowserISOSR import BrowserISOSR, DRIVER_INFO
SRCommand.run(BrowserISOSR, DRIVER_INFO)
''', 0o755)
install(path, dispatcher, path.stat().st_mode & 0o777)
print('Installed browseriso driver, dispatcher adapter, and tapdisk NBD type support.')
print('XAPI discovery/restart is required only for the initial driver registration.')
print('Dispatcher backup: {}'.format(backup / 'SRCommand.py'))
