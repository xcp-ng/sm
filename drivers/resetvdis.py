#!/usr/bin/python3
#
# Copyright (C) Citrix Systems Inc.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published
# by the Free Software Foundation; version 2.1 only.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301  USA
#
# Clear the attach status for all VDIs in the given SR on this host.
# Additionally, reset the paused state if this host is the master.

import cleanup
import util
import lock
import sys
import XenAPI # pylint: disable=import-error


def reset_sr(session, host_uuid, sr_uuid, is_sr_master):
    cleanup.abort(sr_uuid)

    gc_lock = lock.Lock(lock.LOCK_TYPE_GC_RUNNING, sr_uuid)
    sr_lock = lock.Lock(lock.LOCK_TYPE_SR, sr_uuid)
    gc_lock.acquire()
    sr_lock.acquire()

    sr_ref = session.xenapi.SR.get_by_uuid(sr_uuid)

    host_ref = session.xenapi.host.get_by_uuid(host_uuid)
    host_key = "host_%s" % host_ref

    util.SMlog("RESET for SR %s (master: %s)" % (sr_uuid, is_sr_master))

    vdi_recs = session.xenapi.VDI.get_all_records_where( \
            "field \"SR\" = \"%s\"" % sr_ref)

    for vdi_ref, vdi_rec in vdi_recs.items():
        vdi_uuid = vdi_rec["uuid"]
        sm_config = vdi_rec["sm_config"]
        if sm_config.get(host_key):
            util.SMlog("Clearing attached status for VDI %s" % vdi_uuid)
            session.xenapi.VDI.remove_from_sm_config(vdi_ref, host_key)
        if is_sr_master and sm_config.get("paused"):
            util.SMlog("Clearing paused status for VDI %s" % vdi_uuid)
            session.xenapi.VDI.remove_from_sm_config(vdi_ref, "paused")

    sr_lock.release()
    gc_lock.release()


def log_msg(msg, term_output=False):
    util.SMlog(msg)
    if term_output:
        print(msg)


def clean_vdi_status(session, vdi_ref, vdi_uuid, sm_config):
    for key in [cleanup.VDI.DB_VDI_ACTIVATING, cleanup.VDI.DB_VDI_PAUSED]:
        if key in sm_config:
            session.xenapi.VDI.remove_from_sm_config(vdi_ref, key)
            sm_config.pop(key, None)
            log_msg(f"Removed key {key} from VDI {vdi_uuid}")


def reset_vdi(session, vdi_uuid, force, term_output=True, writable=True):
    vdi_ref = session.xenapi.VDI.get_by_uuid(vdi_uuid)
    vdi_rec = session.xenapi.VDI.get_record(vdi_ref)
    sm_config = vdi_rec["sm_config"]
    host_ref = None
    clean = True
    for key, val in sm_config.items():
        if key.startswith("host_"):
            host_ref = key[len("host_"):]
            host_uuid = None
            host_invalid = False
            host_str = host_ref
            try:
                host_rec = session.xenapi.host.get_record(host_ref)
                host_uuid = host_rec["uuid"]
                host_str = "%s (%s)" % (host_uuid, host_rec["name_label"])
            except XenAPI.Failure as e:
                log_msg(f"Invalid host: {host_ref} ({e})", term_output)
                host_invalid = True

            if host_invalid:
                session.xenapi.VDI.remove_from_sm_config(vdi_ref, key)
                log_msg(f"Invalid host: Force-cleared {val} for {vdi_uuid} on host {host_str}", term_output)
                # If the host was invalid, pretend we didn't find if after clearing it.
                host_ref = None
                continue

            if force:
                session.xenapi.VDI.remove_from_sm_config(vdi_ref, key)
                log_msg(f"Force-cleared {val} for {vdi_uuid} on host {host_str}", term_output)
                # If "force" was specified, pretend we didn't find the host after clearing it.
                host_ref = None
                continue

            ret = session.xenapi.host.call_plugin(host_ref, "on-slave", "is_open", {"vdiUuid": vdi_uuid, "srRef": vdi_rec["SR"]})
            if ret == "False":
                session.xenapi.VDI.remove_from_sm_config(vdi_ref, key)
                log_msg(f"Cleared {val} for {vdi_uuid} on host {host_str}", term_output)
                clean_vdi_status(session, vdi_ref, vdi_uuid, sm_config)
            else:
                util.SMlog(f"VDI {vdi_uuid} is still open on host {host_str}, not resetting")
                if term_output:
                    print(f"ERROR: VDI {vdi_uuid} is still open on host {host_str}")
                if writable:
                    return False
                else:
                    clean = False

    if not host_ref:
        # Either we genuinely did not find a host record, or it was invalid or forcibly removed.
        # Therefore we can consider the VDI as not attached and clear the status
        clean_vdi_status(session, vdi_ref, vdi_uuid, sm_config)
        log_msg(f"VDI {vdi_uuid} is not marked as attached anywhere", term_output)
    return clean


def usage():
    print("Usage:")
    print("all <HOST UUID> <SR UUID> [--master]")
    print("single <VDI UUID> [--force]")
    print()
    print("*WARNING!* calling with 'all' on an attached SR, or using " + \
            "--force may cause DATA CORRUPTION if the VDI is still " + \
            "attached somewhere. Always manually double-check that " + \
            "the VDI is not in use before running this script.")
    sys.exit(1)

if __name__ == '__main__':
    import atexit

    if len(sys.argv) not in [3, 4, 5]:
        usage()

    session = XenAPI.xapi_local()
    session.xenapi.login_with_password('root', '', '', 'SM')
    atexit.register(session.xenapi.session.logout)

    mode = sys.argv[1]
    if mode == "all":
        if len(sys.argv) not in [4, 5]:
            usage()
        host_uuid = sys.argv[2]
        sr_uuid = sys.argv[3]
        is_master = False
        if len(sys.argv) == 5:
            if sys.argv[4] == "--master":
                is_master = True
            else:
                usage()
        reset_sr(session, host_uuid, sr_uuid, is_master)
    elif mode == "single":
        vdi_uuid = sys.argv[2]
        force = False
        if len(sys.argv) == 4 and sys.argv[3] == "--force":
            force = True
        reset_vdi(session, vdi_uuid, force)
    elif len(sys.argv) in [3, 4]:
        # backwards compatibility: the arguments for the "all" case used to be
        # just host_uuid, sr_uuid, [is_master] (i.e., no "all" string, since it
        # was the only mode available). To avoid having to change XAPI, accept
        # the old format here as well.
        host_uuid = sys.argv[1]
        sr_uuid = sys.argv[2]
        is_master = False
        if len(sys.argv) == 4:
            if sys.argv[3] == "--master":
                is_master = True
            else:
                usage()
        reset_sr(session, host_uuid, sr_uuid, is_master)
    else:
        usage()
