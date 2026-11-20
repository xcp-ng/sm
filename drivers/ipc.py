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

"""Communication for processes"""

import os
import util
import errno


class IPCFlagException(util.SMException):
    pass


class IPCFlag:
    """Flag-based communication for processes (set, test, clear).
    Not thread-safe."""

    BASE_DIR = "/var/run/sm/ipc"

    def __init__(self, ns):
        self.ns = ns
        self.nsDir = os.path.join(self.BASE_DIR, self.ns)
        if not util.pathexists(self.nsDir):
            try:
                os.makedirs(self.nsDir)
            except OSError:
                pass
        if not util.pathexists(self.nsDir):
            raise IPCFlagException("failed to create %s" % self.nsDir)

    def set(self, name, soft=False):
        """Set the flag

        name: the file to set
        soft: return False if the file exists, instead of raising an Exception.
        returns: True if the file is written,
                 False if soft and the flag exists,
                 else raises an IPCFlagException."""
        flag_file = os.path.join(self.nsDir, name)
        try:
            f = util.open_atomic(flag_file, "w")
            f.write(f"{os.getpid()}\n")
            f.close()
            util.SMlog(f"IPCFlag: set {self.ns}:{name}")
            return True
        except OSError as e:
            if e.errno == errno.EEXIST and soft:
                return False
            raise IPCFlagException(f"failed to create {flag_file}: {e}") from e

    def test(self, name):
        """Test the flag"""
        flagFile = os.path.join(self.nsDir, name)
        return util.pathexists(flagFile)

    def clear(self, name):
        """Clear the flag"""
        if self.test(name):
            flagFile = os.path.join(self.nsDir, name)
            try:
                os.unlink(flagFile)
                util.SMlog("IPCFlag: clear %s:%s" % (self.ns, name))
            except OSError:
                raise IPCFlagException("failed to remove %s" % flagFile)

    def clearAll(self):
        try:
            for file in os.listdir(self.nsDir):
                path = os.path.join(self.nsDir, file)
                os.unlink(path)
        except OSError:
            raise IPCFlagException("failed to remove %s" % path)


def _runTests():
    flag = IPCFlag("A")
    flag.set("X")
    assert flag.test("X")
    flag.clear("X")
    assert not flag.test("X")
    assert not flag.test("Y")
    flag.set("X")
    flag.set("Y")
    flag.set("Z")
    assert flag.test("X")
    assert flag.test("Y")
    assert flag.test("Z")
    flag.clearAll()
    assert not flag.test("X")
    assert not flag.test("Y")
    assert not flag.test("Z")
    print("All tests passed")

if __name__ == '__main__':
    _runTests()
