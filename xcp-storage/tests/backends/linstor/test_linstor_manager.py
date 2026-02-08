#!/usr/bin/env python3
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

from xcp_storage.backends.linstor.manager import (
    LinstorManager,
    VolumeDetails,
)

# ==============================================================================

class TestLinstorManager:
    def test_can_controller_force_place_volumes(self) -> None:
        can_controller_force_place_volumes = LinstorManager.can_controller_force_place_volumes

        assert can_controller_force_place_volumes([
            VolumeDetails(-1, -1, -1, "")
        ])

        assert can_controller_force_place_volumes([
            VolumeDetails(-1, -1, -1, "a")
        ])

        assert can_controller_force_place_volumes([
            VolumeDetails(-1, -1, -1, ""),
            VolumeDetails(-1, -1, -1, "")
        ])

        assert can_controller_force_place_volumes([
            VolumeDetails(-1, -1, -1, "a"),
            VolumeDetails(-1, -1, -1, "")
        ])

        assert can_controller_force_place_volumes([
            VolumeDetails(-1, -1, -1, "a"),
            VolumeDetails(-1, -1, -1, "b")
        ])

        assert can_controller_force_place_volumes([
            VolumeDetails(-1, -1, -1, ""),
            VolumeDetails(-1, -1, -1, ""),
            VolumeDetails(-1, -1, -1, ""),
        ])

        assert can_controller_force_place_volumes([
            VolumeDetails(-1, -1, -1, "a"),
            VolumeDetails(-1, -1, -1, "a"),
            VolumeDetails(-1, -1, -1, "a"),
        ])

        assert can_controller_force_place_volumes([
            VolumeDetails(-1, -1, -1, "a"),
            VolumeDetails(-1, -1, -1, ""),
            VolumeDetails(-1, -1, -1, ""),
        ])

        assert can_controller_force_place_volumes([
            VolumeDetails(-1, -1, -1, "a"),
            VolumeDetails(-1, -1, -1, "a"),
            VolumeDetails(-1, -1, -1, ""),
        ])

        assert not can_controller_force_place_volumes([
            VolumeDetails(-1, -1, -1, "a"),
            VolumeDetails(-1, -1, -1, "b"),
            VolumeDetails(-1, -1, -1, ""),
        ])
