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

from dataclasses import asdict

from xcp_storage.backends.drbd import get_drbd_local_openers
from xcp_storage.rpc.dispatcher import ApiDispatcher
from xcp_storage.utils.json import JsonDict

from xcp_storage.typing import List

# ==============================================================================

@ApiDispatcher.method
def get_openers(resource_name: str, volume_number: int) -> List[JsonDict]:
    return [asdict(opener) for opener in get_drbd_local_openers(resource_name, volume_number)]
