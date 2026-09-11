#!/usr/bin/python3
#
# Copyright (C) 2026  Vates SAS
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

import sys
import os
sys.path.append("/opt/xensource/sm/")
import lvutil
import util
from lvmcache import LVMCache


def master_only(func):
    def wrapper(session, args):
        if not util.is_master(session):
            raise util.SMException(f"{func.__name__} must be called on master")
        return func(session, args)
    return wrapper


@master_only
def delete_cbt_log(session, args):
    util.SMlog(f"on_master.delete_cbt_log: {args}")
    os.environ['LVM_SYSTEM_DIR'] = lvutil.MASTER_LVM_CONF
    vgName = args["vgName"]
    lvName = args["lvName"]
    try:
        lvmcache = LVMCache(vgName)
        if lvmcache.checkLV(lvName):
            lvmcache.remove(lvName)
    except util.CommandException as e:
        util.SMlog(f"on_master.delete_cbt_log: failed to remove {lvName}: {e}")
        raise
    return "True"


if __name__ == "__main__":
    import XenAPIPlugin
    XenAPIPlugin.dispatch({
        "delete_cbt_log": delete_cbt_log,
    })
