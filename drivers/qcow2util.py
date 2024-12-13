#!/usr/bin/env python3
#
# Copyright (C) 2024  Vates SAS
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

from sm_typing import Callable, Dict, Optional, cast, override

from cowutil import CowImageInfo, CowUtil

# ------------------------------------------------------------------------------

class QCow2Util(CowUtil):
    @override
    def getMinImageSize(self) -> int:
        return 0

    @override
    def getMaxImageSize(self) -> int:
        return 0

    @override
    def getBlockSize(self, path: str) -> int:
        return 0

    @override
    def getFooterSize(self) -> int:
        return 0

    @override
    def getDefaultPreallocationSizeVirt(self) -> int:
        return 0

    @override
    def getMaxChainLength(self) -> int:
        return 0

    @override
    def calcOverheadEmpty(self, virtual_size: int) -> int:
        return 0

    @override
    def calcOverheadBitmap(self, virtual_size: int) -> int:
        return 0

    @override
    def getInfo(
        self,
        path: str,
        extractUuidFunction: Callable[[str], str],
        includeParent: bool = True,
        resolveParent: bool = True,
        useBackupFooter: bool = False
    ) -> CowImageInfo:
        return CowImageInfo("Unknown")

    @override
    def getInfoFromLVM(
        self, lvName: str, extractUuidFunction: Callable[[str], str], vgName: str
    ) -> Optional[CowImageInfo]:
        return None

    @override
    def getAllInfoFromVG(
        self,
        pattern: str,
        extractUuidFunction: Callable[[str], str],
        vgName: Optional[str] = None,
        parents: bool = False,
        exitOnError: bool = False
    ) -> Dict[str, CowImageInfo]:
        return dict()

    @override
    def getParent(self, path: str, extractUuidFunction: Callable[[str], str]) -> Optional[str]:
        return None

    @override
    def getParentNoCheck(self, path: str) -> Optional[str]:
        return None

    @override
    def hasParent(self, path: str) -> bool:
        return False

    @override
    def setParent(self, path: str, parentPath: str, parentRaw: bool) -> None:
        return

    @override
    def getHidden(self, path: str) -> bool:
        return False

    @override
    def setHidden(self, path: str, hidden: bool = True) -> None:
        return

    @override
    def getSizeVirt(self, path: str) -> int:
        return 0

    @override
    def setSizeVirt(self, path: str, size: int, jFile: str) -> None:
        return

    @override
    def setSizeVirtFast(self, path: str, size: int) -> None:
        return

    @override
    def getMaxResizeSize(self, path: str) -> int:
        return 0

    @override
    def getSizePhys(self, path: str) -> int:
        return 0

    @override
    def setSizePhys(self, path: str, size: int, debug: bool = True) -> None:
        return

    @override
    def getAllocatedSize(self, path: str) -> int:
        return 0

    @override
    def getResizeJournalSize(self) -> int:
        return 0

    @override
    def killData(self, path: str) -> None:
        return

    @override
    def getDepth(self, path: str) -> int:
        return 0

    @override
    def getBlockBitmap(self, path: str) -> bytes:
        return b""

    @override
    def coalesce(self, path: str) -> int:
        return 0

    @override
    def create(self, path: str, size: int, static: bool, msize: int = 0) -> None:
        return

    @override
    def snapshot(
        self,
        path: str,
        parent: str,
        parentRaw: bool,
        msize: int = 0,
        checkEmpty: bool = True
    ) -> None:
        return

    @override
    def canSnapshotRaw(self, size: int) -> bool:
        return False

    @override
    def check(
        self,
        path: str,
        ignoreMissingFooter: bool = False,
        fast: bool = False
    ) -> CowUtil.CheckResult:
        return CowUtil.CheckResult.Fail

    @override
    def revert(self, path: str, jFile: str) -> None:
        return

    @override
    def repair(self, path: str) -> None:
        return

    @override
    def validateAndRoundImageSize(self, size: int) -> int:
        return 0

    @override
    def getKeyHash(self, path: str) -> Optional[str]:
        return None

    @override
    def setKey(self, path: str, key_hash: str) -> None:
        return
