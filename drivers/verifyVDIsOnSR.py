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
# Tool to check all COW-based VDIs (VHD, QCOW2) belonging to a VG/SR.
# Usage is "./verifyVDIsOnSR.py <sr_uuid>". This tool verifies all the VDIs
# on a COW-based LVM SR. (FC or iSCSI)
#

import os
import sys
import util
import lvutil


from constants import NS_PREFIX_LVM, VG_LOCATION, VG_PREFIX
from cowutil import getCowUtil
from lock import Lock
from lvmcowutil import LV_PREFIX, LvmCowUtil
from refcounter import RefCounter
from vditype import VDI_COW_TYPES

# Stores the vdi activated, comes handy while deactivating
VDIs_passed = 0
VDIs_failed = 0


def activateVdiChainAndCheck(cowutil, image_info, vg_name):
    global VDIs_passed
    global VDIs_failed
    activated_list = []
    vdi_path = os.path.join(VG_LOCATION, vg_name, image_info.path)
    sr_uuid = vg_name[len(VG_PREFIX):]
    if not activateVdi(
                       sr_uuid,
                       image_info.uuid,
                       vdi_path):
        # If activation fails, do not run check, also no point on running
        # check on the VDIs down the chain
        util.SMlog("VDI activate failed for %s, skipping rest of VDI chain" %
                    vg_name)
        return activated_list

    activated_list.append([image_info.uuid, vdi_path])

    # Do a vhdutil check with -i option, to ignore error in primary
    if cowutil.check(vdi_path, True) != cowutil.CheckResult.Success:
        util.SMlog("VDI check for %s failed, continuing with the rest!" % vg_name)
        VDIs_failed += 1
    else:
        VDIs_passed += 1

    if hasattr(image_info, 'children'):
        for image_info_sub in image_info.children:
            activated_list.extend(activateVdiChainAndCheck(cowutil, image_info_sub, vg_name))

    return activated_list


def activateVdi(sr_uuid, vdi_uuid, vdi_path):
    name_space = NS_PREFIX_LVM + sr_uuid
    lock = Lock(vdi_uuid, name_space)
    lock.acquire()
    try:
        count = RefCounter.get(vdi_uuid, False, name_space)
        if count == 1:
            try:
                lvutil.activateNoRefcount(vdi_path, False)
            except Exception as e:
                util.SMlog("  lv activate failed for %s with error %s" %
                           (vdi_path, str(e)))
                RefCounter.put(vdi_uuid, False, name_space)
                return False
    finally:
        lock.release()

    return True


def deactivateVdi(sr_uuid, vdi_uuid, vdi_path):
    name_space = NS_PREFIX_LVM + sr_uuid
    lock = Lock(vdi_uuid, name_space)
    lock.acquire()
    try:
        count = RefCounter.put(vdi_uuid, False, name_space)
        if count > 0:
            return
        try:
            lvutil.deactivateNoRefcount(vdi_path)
        except Exception as e:
            util.SMlog("  lv de-activate failed for %s with error %s" %
                       (vdi_path, str(e)))
            RefCounter.get(vdi_uuid, False, name_space)
    finally:
        lock.release()


def checkAllVDI(sr_uuid):
    activated_list = []
    VDIs_total = 0

    vg_name = VG_PREFIX + sr_uuid
    for vdi_type in VDI_COW_TYPES:
        vdi_trees = []
        pattern = "%s*" % LV_PREFIX[vdi_type]

        cowutil = getCowUtil(vdi_type)
        vdis = cowutil.getAllInfoFromVG(pattern, LvmCowUtil.extractUuid, vg_name)
        VDIs_total += len(vdis)

        # Build VDI chain, that way it will be easier to activate all the VDIs
        # that belong to one chain, do check on the same and then deactivate
        for vdi in vdis:
            if vdis[vdi].parentUuid:
                parent_VDI_info = vdis.get(vdis[vdi].parentUuid)
                if not hasattr(parent_VDI_info, 'children'):
                    parent_VDI_info.children = []
                parent_VDI_info.children.append(vdis[vdi])
            else:
                vdi_trees.append(vdis[vdi])

        # If needed, activate VDIs belonging to each VDI chain, do a check on
        # all VDIs and then set the state back.
        for vdi_chain in vdi_trees:
            activated_list = activateVdiChainAndCheck(cowutil, vdi_chain, vg_name)

            #Deactivate the LVs, states are maintained by Refcounter
            for item in activated_list:
                deactivateVdi(sr_uuid, item[0], item[1])

    print("VDIs check passed on %d, failed on %d, not run on %d" %
          (VDIs_passed, VDIs_failed, VDIs_total - (VDIs_passed + VDIs_failed)))

if __name__ == '__main__':
    if len(sys.argv) == 1:
        print("Usage:")
        print("/opt/xensource/sm/verifyVDIsOnSR.py <sr_uuid>")
    else:
        checkAllVDI(sys.argv[1])
