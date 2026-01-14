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

import argparse
from collections import defaultdict
import contextlib
from enum import IntEnum
import functools
import re

import linstor

import xcp_storage.log as log
from xcp_storage.utils.process import run_command
from xcp_storage.utils.sync import wait_for_condition

from xcp_storage.typing import (
    Any,
    Callable,
    cast,
    Collection,
    Concatenate,
    Dict,
    List,
    Never,
    Optional,
    override,
    ParamSpec,
    Sequence,
    Set,
    Tuple,
    TypeVar,
    Union,
)

P = ParamSpec("P")
T = TypeVar("T")

# ==============================================================================

LINSTOR_SATELLITE_PORT = 3366

# ------------------------------------------------------------------------------

def _get_controller_addresses() -> List[str]:
    stdout = run_command([
        "/usr/sbin/ss", "-tnpH", "state", "established", f"( sport = :{LINSTOR_SATELLITE_PORT} )"
    ], expected_ret_code=0)
    return [
        line.split()[3].rsplit(":", 1)[0]
        for line in stdout.splitlines()
    ]

def _get_controller_uri() -> str:
    # TODO: Check that an IP address from the current pool is returned.
    addresses = _get_controller_addresses()
    return "linstor://" + addresses[0] if addresses else ""

# ------------------------------------------------------------------------------

class LinstorManagerError(Exception):
    SHIFT_FETCH   = 2
    SHIFT_CREATE  = 5
    SHIFT_DESTROY = 8
    SHIFT_OTHER   = 11

    # Global (0x0003).
    ERR_NONE    = 0
    ERR_GENERIC = 1
    ERR_NETWORK = 2

    # Fetch (0x001C).
    ERR_NODE_FETCH                = 1 << SHIFT_FETCH
    ERR_STORAGE_POOL_FETCH        = 2 << SHIFT_FETCH
    ERR_RESOURCE_GROUP_FETCH      = 3 << SHIFT_FETCH
    ERR_RESOURCE_DEFINITION_FETCH = 4 << SHIFT_FETCH
    ERR_RESOURCE_FETCH            = 5 << SHIFT_FETCH

    # Create (0x00E0).
    ERR_NODE_CREATE                = 1 << SHIFT_CREATE
    ERR_NODE_INTERFACE_CREATE      = 2 << SHIFT_CREATE
    ERR_STORAGE_POOL_CREATE        = 3 << SHIFT_CREATE
    ERR_RESOURCE_GROUP_CREATE      = 4 << SHIFT_CREATE
    ERR_RESOURCE_DEFINITION_CREATE = 5 << SHIFT_CREATE
    ERR_RESOURCE_CREATE            = 6 << SHIFT_CREATE

    # Destroy (0x0700).
    ERR_NODE_DESTROY                = 1 << SHIFT_DESTROY
    ERR_NODE_INTERFACE_DESTROY      = 2 << SHIFT_DESTROY
    ERR_STORAGE_POOL_DESTROY        = 3 << SHIFT_DESTROY
    ERR_RESOURCE_GROUP_DESTROY      = 4 << SHIFT_DESTROY
    ERR_RESOURCE_DEFINITION_DESTROY = 5 << SHIFT_DESTROY
    ERR_RESOURCE_DESTROY            = 6 << SHIFT_DESTROY

    # Other.
    ERR_NODE_NOT_EXISTS                 = 1 << SHIFT_OTHER
    ERR_NODE_INTERFACE_MODIFY           = 2 << SHIFT_OTHER
    ERR_NODE_INTERFACE_NOT_EXISTS       = 3 << SHIFT_OTHER

    ERR_RESOURCE_GROUP_NOT_EXISTS       = 4 << SHIFT_OTHER

    ERR_RESOURCE_DEFINITION_EXISTS      = 5 << SHIFT_OTHER
    ERR_RESOURCE_DEFINITION_NOT_EXISTS  = 6 << SHIFT_OTHER
    ERR_RESOURCE_DEFINITION_PROP_UPDATE = 7 << SHIFT_OTHER

    ERR_RESOURCE_TOGGLE                 = 8 << SHIFT_OTHER
    ERR_RESOURCE_PROP_UPDATE            = 9 << SHIFT_OTHER

    def __init__(self, message: str, flags: int = ERR_GENERIC) -> None:
        super().__init__(message)
        self._flags = flags

    @property
    def flags(self) -> int:
        return self._flags

# ------------------------------------------------------------------------------

class LinstorManagerBase:
    def __init__(self, uri: Optional[str] = None) -> None:
        self._linstor: Optional[linstor.Linstor] = None
        self._uri = uri

    def connect(self) -> None:
        if self._linstor:
            return

        uri = None
        def connect_impl() -> bool:
            nonlocal uri

            try:
                if self._uri:
                    uri = self._uri
                else:
                    uri = self.find_controller_uri(timeout=0)
                    if not uri:
                        return False

                instance = linstor.Linstor(uri, timeout=5, keep_alive=True)
                instance.connect()
                self._linstor = instance
                self._uri = uri
                return True
            except (linstor.errors.LinstorNetworkError, linstor.errors.LinstorTimeoutError):
                pass
            except Exception as e:
                log.error(f"Unable to connect to LINSTOR: `{e}`.")
            return False

        if wait_for_condition(connect_impl, timeout=120, interval=1):
            return

        self._uri = None
        if not uri:
            raise LinstorManagerError(
                "Unable to find controller uri...",
                LinstorManagerError.ERR_NETWORK
            )

        raise LinstorManagerError(
            f"Unable to connect to LINSTOR with URI: `{uri}`.",
            LinstorManagerError.ERR_NETWORK
        )

    @staticmethod
    def find_controller_uri(timeout: int = 30) -> Optional[str]:
        return wait_for_condition(_get_controller_uri, timeout, interval=1)

    def _exec_query(self, query: Callable[Concatenate[linstor.Linstor, P], T], *args: P.args, **kwargs: P.kwargs) -> T:
        while True:
            self.connect()
            assert self._linstor
            try:
                return query(self._linstor, *args, **kwargs)
            except (linstor.errors.LinstorNetworkError, linstor.errors.LinstorTimeoutError):
                self._linstor = None
            except Exception as e:
                raise LinstorManagerError(f"LINSTOR query exception: `{e}`.") from e

    @staticmethod
    def _filter_errors(result: Sequence[linstor.responses.RESTMessageResponse]) -> List[linstor.responses.ApiCallResponse]:
        return [
            cast(linstor.responses.ApiCallResponse, err) for err in result
            if hasattr(err, "is_error") and err.is_error()
        ]

    @staticmethod
    def _find_error(
        result: List[linstor.responses.ApiCallResponse], codes: Tuple[str, ...]
    ) -> Optional[linstor.responses.ApiCallResponse]:
        for err in result:
            for code in codes:
                if err.is_error(code):
                    return err
        return None

    @classmethod
    def _get_error_str(cls, result: Sequence[linstor.responses.RESTMessageResponse]) -> str:
        return ", ".join([
            err.message for err in cls._filter_errors(result)
        ])

# ------------------------------------------------------------------------------

class LinstorManager(LinstorManagerBase):
    # Represent the number of possible connections from a
    # local resource to its replicas (diskless + diskful).
    # Thus, with a value of 3, 4 instances of a resource can be created.
    MAX_PEERS = 3

    DEFAULT_PLACE_COUNT = 2

    _ERR_MSG_NO_DATA = "no data"
    _ERR_MSG_NODE_NOT_EXISTS = "node doesn't exist"
    _ERR_MSG_NODE_INTERFACE_NOT_EXISTS = "node interface doesn't exist"
    _ERR_MSG_RESOURCE_DEFINITION_EXISTS = "definition exists"
    _ERR_MSG_RESOURCE_DEFINITION_NOT_EXISTS = "definition doesn't exist"
    _ERR_MSG_RESOURCE_GROUP_NOT_EXISTS = "group doesn't exist"

    # ----------------------------------
    # Controller helpers.
    # ----------------------------------

    class StoragePoolStats:
        def __init__(self, name: str, node_name: str, free_size: int, capacity: int) -> None:
            self.name = name
            self.node_name = node_name
            self.free_size = free_size
            self.capacity = capacity

        @override
        def __repr__(self) -> str:
            return f"StoragePoolStats({self.name}, {self.node_name}, {self.free_size}, {self.capacity})"

    class ResourceReplicasMode(IntEnum):
        # Fetch all replicas.
        ALL = 0
        # Only fetch replicas when there is a risk of split brain or an insufficient number of diskfuls.
        MISSING_ONLY = 1
        # Same as above, but check that there are enough up-to-date diskfuls to avoid data loss.
        STRICT_DATA_INTEGRITY = 2

    class ResourceReplicas:
        def __init__(
            self,
            name: str,
            diskful_node_names: List[str],
            diskless_node_names: List[str],
            up_to_date_node_names: List[str],
            diskful_count: int,
            diskless_count: int,
            up_to_date_count: int,
            storage_pool_names: List[str],
            expected_place_count: int
        ) -> None:
            self.name = name
            self.diskful_node_names = diskful_node_names
            self.diskless_node_names = diskless_node_names
            self.up_to_date_node_names = up_to_date_node_names

            # Count is the value AFTER evacuation of specific nodes.
            # Therefore, it can be smaller than the size of the node lists.
            self.diskful_count = diskful_count
            self.diskless_count = diskless_count
            self.up_to_date_count = up_to_date_count

            self.storage_pool_names = storage_pool_names
            self.expected_place_count = expected_place_count

        @property
        def missing_diskful_count(self) -> int:
            return max(self.expected_place_count - self.diskful_count, 0)

        @property
        def missing_diskless_count(self) -> int:
            return max(3 - self.expected_place_count + self.diskless_count, 0)

        @override
        def __repr__(self) -> str:
            return ("ResourceReplicas("
                f"{self.name}, "
                f"{self.diskful_count}:{self.diskful_node_names}, "
                f"{self.diskless_count}:{self.diskless_node_names}, "
                f"{self.up_to_date_count}:{self.up_to_date_node_names}, "
                f"{self.storage_pool_names}, {self.expected_place_count}"
            ")")

    def get_controller_mismatched_nodes(self) -> List[str]:
        return [node.name for node in self._fetch_nodes().values() if node.connection_status == "VERSION_MISMATCH"]

    def get_controller_storage_pool_stats(self) -> Dict[str, List[StoragePoolStats]]:
        storage_pools_stats: Dict[str, List[LinstorManager.StoragePoolStats]] = {}
        for storage_pool_name, storage_pools in self._fetch_storage_pools().items():
            current_list = storage_pools_stats[storage_pool_name] = []
            for storage_pool in storage_pools:
                free_size = -1
                capacity = -1

                space = storage_pool.free_space
                if space and space.free_capacity >= 0 and space.total_capacity >= 0:
                    free_size = space.free_capacity * 1024
                    capacity = space.total_capacity * 1024

                current_list.append(self.StoragePoolStats(
                    storage_pool_name,
                    storage_pool.node_name,
                    free_size,
                    capacity
                ))
        return storage_pools_stats

    def get_controller_resource_names(
        self,
        group_names: Optional[Set[str]] = None,
        ignore_deleted: bool = True
    ) -> Set[str]:
        resource_definitions = self._fetch_resource_definitions()
        resource_groups = self._fetch_resource_groups()

        resource_names = set()
        for resource_definition in resource_definitions.values():
            if (not group_names or resource_definition.resource_group_name in resource_groups) and (
                ignore_deleted or not self._is_deleting_resource(resource_definition)
            ):
                resource_names.add(resource_definition.name)
        return resource_names

    def get_controller_resource_replicas( # noqa: C901
        self,
        group_names: Optional[Set[str]] = None,
        excluded_node_names: Optional[Set[str]] = None,
        mode: ResourceReplicasMode = ResourceReplicasMode.ALL
    ) -> List[ResourceReplicas]:
        # `excluded_node_names` can be used to simulate a node evacuate.

        resource_replicas = []
        resource_groups = self._fetch_resource_groups(group_names)
        if not resource_groups:
            return []

        nodes = self._fetch_nodes()

        resource_entries = self._fetch_resource_entries()
        name_to_resource_definitions = self._fetch_resource_definitions()
        for resource_definition in name_to_resource_definitions.values():
            group_name = resource_definition.resource_group_name
            resource_group = resource_groups.get(group_name)
            if not resource_group:
                continue

            resource_entry = resource_entries.get(resource_definition.name)
            if not resource_entry:
                continue

            diskful_node_names = []
            diskless_node_names = []
            up_to_date_node_names = []
            for resource in resource_entry.resources:
                if not self._is_placed_resource(resource):
                    continue

                node = nodes.get(resource.node_name)
                if not node:
                    continue # In theory can only be reached if there is a race condition or a bug in API.
                if self._is_evacuating_node(node):
                    continue

                if self._is_diskless_resource(resource):
                    diskless_node_names.append(resource.node_name)
                else:
                    diskful_node_names.append(resource.node_name)
                    if all(map(self._is_up_to_date_volume, resource.volumes)):
                        up_to_date_node_names.append(resource.node_name)

            if excluded_node_names:
                def count_helper(node_names: List[str]) -> int:
                    return sum(node_name not in excluded_node_names for node_name in node_names)

                diskful_count = count_helper(diskful_node_names)
                diskless_count = count_helper(diskless_node_names)
                up_to_date_count = count_helper(up_to_date_node_names)
            else:
                diskful_count = len(diskful_node_names)
                diskless_count = len(diskless_node_names)
                up_to_date_count = len(up_to_date_node_names)

            expected_place_count = self._get_resource_group_place_count(resource_group)
            if (
                # All.
                mode == self.ResourceReplicasMode.ALL or
                # Simple checks.
                (diskful_count < expected_place_count or diskful_count + diskless_count < 3) or
                # Strict.
                (
                    mode == self.ResourceReplicasMode.STRICT_DATA_INTEGRITY and
                    expected_place_count >= 2 and
                    up_to_date_count < 2
                )
            ):
                resource_replicas.append(self.ResourceReplicas(
                    resource_definition.name,
                    diskful_node_names,
                    diskless_node_names,
                    up_to_date_node_names,
                    diskful_count,
                    diskless_count,
                    up_to_date_count,
                    resource_group.select_filter.storage_pool_list,
                    expected_place_count
                ))

        return resource_replicas

    def remove_controller_skip_disks(self) -> None:
        # This method MUST only be called to destroy diskful with invalid resources.
        resource_entries = self._fetch_resource_entries()

        for resource_entry in resource_entries.values():
            resources = resource_entry.resources
            skip_disk_resources = {
                resource.node_name: resource
                for resource in resources
                if self._is_skip_disk_resource(resource)
            }
            # Skip disk deletion is only permitted if at least one remaining volume is in a stable state.
            if not any(
                self._is_active_resource(resource) and all(map(self._is_up_to_date_volume, resource.volumes))
                for resource in resources
                if resource.node_name not in skip_disk_resources
                for volume in resource.volumes
            ):
                continue

            for resource in skip_disk_resources.values():
                try:
                    if self._is_diskless_resource(resource):
                        self.toggle_resource(resource.name, resource.node_name, True)
                    self.remove_resource_skip_disk_flag(resource.name, resource.node_name)
                except LinstorManagerError as e:
                    if e.flags & LinstorManagerError.ERR_NETWORK:
                        raise
                    log.warning(
                        f"Failed to delete skip disk on resource `{resource.name}` "
                        f"on node `{resource.node_name}`: `{e}`."
                    )

    # ----------------------------------
    # Node helpers.
    # ----------------------------------

    class NodeInterface:
        def __init__(self, name: str, address: str, active: bool) -> None:
            self.name = name
            self.address = address
            self.active = active

        @override
        def __repr__(self) -> str:
            return f"NodeInterface({self.name}, {self.address}, {self.active})"

    def create_node(self, node_name: str, ip: str) -> None:
        errors = self._filter_errors(self._exec_query(
            linstor.Linstor.node_create,
            node_name=node_name,
            node_type=linstor.consts.VAL_NODE_TYPE_CMBD,
            ip=ip
        ))
        if not errors:
            self.invalidate_node_cache()
            return

        raise LinstorManagerError(
            f"Failed to create node `{node_name}`: `{self._get_error_str(errors)}`.",
            LinstorManagerError.ERR_NODE_CREATE
        )

    def destroy_node(self, node_name: str) -> None:
        errors = self._filter_errors(self._exec_query(linstor.Linstor.node_delete, node_name))
        if not errors:
            self.invalidate_node_cache()
            self.invalidate_storage_pool_cache()
            self.invalidate_resource_definition_cache()
            self.invalidate_resource_cache()
            return

        if not self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_NODE, )):
            raise LinstorManagerError(
                f"Failed to destroy node `{node_name}`: `{self._get_error_str(errors)}`.",
                LinstorManagerError.ERR_NODE_DESTROY
            )

    def get_node_interfaces(self, node_name: str) -> List[NodeInterface]:
        node = self._fetch_one_node(node_name)
        if not node:
            raise LinstorManagerError(
                f"Failed to get interfaces on node `{node_name}`: `{self._ERR_MSG_NODE_NOT_EXISTS}`.",
                LinstorManagerError.ERR_NODE_NOT_EXISTS
            )

        return [
            self.NodeInterface(interface.name, interface.address, interface.is_active)
            for interface in node.net_interfaces
        ]

    def get_node_preferred_interface_name(self, node_name: str) -> str:
        node = self._fetch_one_node(node_name)
        if not node:
            raise LinstorManagerError(
                f"Failed to get preferred interface on node `{node_name}`: `{self._ERR_MSG_NODE_NOT_EXISTS}`.",
                LinstorManagerError.ERR_NODE_NOT_EXISTS
            )

        return node.properties.get("PrefNic", "default")

    def set_node_preferred_interface_name(self, node_name: str, interface_name: str) -> None:
        self.invalidate_node_cache()
        errors = self._filter_errors(self._exec_query(
            linstor.Linstor.node_modify,
            node_name=node_name,
            property_dict={"PrefNic": interface_name}
        ))
        if not errors:
            return

        def raise_error(reason: str, flags: int = 0) -> Never:
            raise LinstorManagerError(
                f"Failed to set node preferred interface `{interface_name}` on node `{node_name}`: `{reason}`.",
                LinstorManagerError.ERR_NODE_INTERFACE_MODIFY | flags
            )

        if self._find_error(errors, (linstor.consts.FAIL_INVLD_PROP, )):
            raise_error(self._ERR_MSG_NODE_INTERFACE_NOT_EXISTS, LinstorManagerError.ERR_NODE_INTERFACE_NOT_EXISTS)
        raise_error(self._get_error_str(errors))

    # ----------------------------------
    # Node interface helpers.
    # ----------------------------------

    def create_node_interface(self, interface_name: str, node_name: str, ip: str) -> None:
        errors = self._filter_errors(self._exec_query(
            linstor.Linstor.netinterface_create,
            node_name=node_name,
            interface_name=interface_name,
            ip=ip
        ))
        if not errors:
            self.invalidate_node_cache()
            return

        def raise_error(reason: str, flags: int = 0) -> Never:
            raise LinstorManagerError(
                f"Failed to create node interface `{interface_name}` on node `{node_name}`: `{reason}`.",
                LinstorManagerError.ERR_NODE_INTERFACE_CREATE | flags
            )

        if self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_NODE, )):
            raise_error(self._ERR_MSG_NODE_NOT_EXISTS, LinstorManagerError.ERR_NODE_NOT_EXISTS)
        raise_error(self._get_error_str(errors))

    def destroy_node_interface(self, interface_name: str, node_name: str) -> None:
        if interface_name == "default":
            raise LinstorManagerError(
                "Unable to delete the default interface of a node!",
                LinstorManagerError.ERR_NODE_INTERFACE_DESTROY
            )

        errors = self._filter_errors(self._exec_query(
            linstor.Linstor.netinterface_delete,
            node_name=node_name,
            interface_name=interface_name
        ))
        if not errors:
            # Note: If the interface is not present, this branch is executed.
            self.invalidate_node_cache()
            return

        raise LinstorManagerError(
            f"Failed to destroy node interface `{interface_name}` on node `{node_name}`: "
            f"`{self._get_error_str(errors)}`.",
            LinstorManagerError.ERR_NODE_INTERFACE_DESTROY
        )

    def modify_node_interface(self, interface_name: str, node_name: str, ip: str) -> None:
        self.invalidate_node_cache()
        errors = self._filter_errors(self._exec_query(
            linstor.Linstor.netinterface_create,
            node_name=node_name,
            interface_name=interface_name,
            ip=ip
        ))
        if not errors:
            return

        def raise_error(reason: str, flags: int = 0) -> Never:
            raise LinstorManagerError(
                f"Failed to modify node interface `{interface_name}` on node `{node_name}`: `{reason}`.",
                LinstorManagerError.ERR_NODE_INTERFACE_MODIFY | flags
            )

        if self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_NODE, )):
            raise_error(self._ERR_MSG_NODE_NOT_EXISTS, LinstorManagerError.ERR_NODE_NOT_EXISTS)
        if not self._find_error(errors, (linstor.consts.FAIL_EXISTS_NET_IF, )):
            raise_error(self._get_error_str(errors))

        errors = self._filter_errors(self._exec_query(
            linstor.Linstor.netinterface_modify,
            node_name=node_name,
            interface_name=interface_name,
            ip=ip
        ))
        if not errors:
            return

        if self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_NODE, )):
            raise_error(self._ERR_MSG_NODE_NOT_EXISTS, LinstorManagerError.ERR_NODE_NOT_EXISTS)
        raise_error(self._get_error_str(errors))

    # ----------------------------------
    # Storage pool helpers.
    # ----------------------------------

    def create_storage_pool(
        self,
        storage_pool_name: str,
        node_name: str,
        backing_device_path: str,
        thin_provisioning: bool
    ) -> None:
        if thin_provisioning:
            backing_device_parts = backing_device_path.split("/")
            if not len(backing_device_parts) == 2:
                raise LinstorManagerError(
                    "Invalid backing device path format for thin provisioning. Expected format: `VG/LV`."
                )

        while True:
            errors = self._filter_errors(self._exec_query(
                linstor.Linstor.storage_pool_create,
                node_name=node_name,
                storage_pool_name=storage_pool_name,
                storage_driver="LVM_THIN" if thin_provisioning else "LVM",
                driver_pool_name=backing_device_path
            ))
            if not errors:
                self.invalidate_storage_pool_cache()
                break

            def raise_error(reason: str, flags: int = 0) -> Never:
                raise LinstorManagerError(
                    f"Failed to create storage pool `{storage_pool_name}` on node `{node_name}`: `{reason}`.",
                    LinstorManagerError.ERR_STORAGE_POOL_CREATE | flags
                )

            if len(errors) == 1 and errors[0].is_error(
                linstor.consts.FAIL_STOR_POOL_CONFIGURATION_ERROR
            ) and re.match(".*Volume group '.*' not found$", errors[0].message):
                self.destroy_storage_pool(storage_pool_name, node_name)
                continue

            if self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_NODE, )):
                raise_error(self._ERR_MSG_NODE_NOT_EXISTS, LinstorManagerError.ERR_NODE_NOT_EXISTS)

            raise_error(self._get_error_str(errors))

    def destroy_storage_pool(self, storage_pool_name: str, node_name: str) -> None:
        errors = []
        def destroy_impl() -> bool:
            nonlocal errors
            errors = self._filter_errors(self._exec_query(
                linstor.Linstor.storage_pool_delete,
                node_name=node_name,
                storage_pool_name=storage_pool_name
            ))
            if not errors:
                self.invalidate_storage_pool_cache()
                return True

            return bool(self._find_error(errors, (
                linstor.consts.FAIL_NOT_FOUND_STOR_POOL,
                linstor.consts.FAIL_NOT_FOUND_STOR_POOL_DFN
            )))

        # We must retry to avoid errors like:
        # "can not be deleted as volumes / snapshot-volumes are still using it".
        if not wait_for_condition(destroy_impl, timeout=30, interval=1):
            raise LinstorManagerError(
                f"Failed to destroy storage pool `{storage_pool_name}` on node `{node_name}`: "
                f"`{self._get_error_str(errors)}`.",
                LinstorManagerError.ERR_STORAGE_POOL_DESTROY
            )

    # ----------------------------------
    # Resource group helpers.
    # ----------------------------------

    class ResourceGroupStats:
        def __init__(self, name: str, free_size: int, capacity: int, virtual_capacity: int) -> None:
            self.name = name
            self.free_size = free_size
            self.used_size = max(capacity - free_size, 0)
            self.capacity = capacity
            self.virtual_capacity = virtual_capacity

        @override
        def __repr__(self) -> str:
            return ("ResourceGroupStats("
                f"{self.name}, {self.free_size}, {self.used_size}, {self.capacity}, {self.virtual_capacity}"
            ")")

    def create_resource_group(
        self,
        group_name: str,
        storage_pool_names: List[str],
        place_count: int,
        destroy_old_group: bool = False
    ) -> None:
        # 1. Create resource group.
        rg_creation_attempt = 0
        while True:
            errors = self._filter_errors(self._exec_query(
                linstor.Linstor.resource_group_create,
                name=group_name,
                place_count=place_count,
                storage_pool=storage_pool_names,
                diskless_on_remaining=False
            ))
            if not errors:
                self.invalidate_resource_group_cache()
                break

            if destroy_old_group and self._find_error(errors, (linstor.consts.FAIL_EXISTS_RSC_GRP, )):
                rg_creation_attempt += 1
                if rg_creation_attempt < 2:
                    try:
                        self.destroy_resource_group(group_name)
                    except LinstorManagerError as e:
                        if e.flags & LinstorManagerError.ERR_RESOURCE_GROUP_DESTROY:
                            raise LinstorManagerError(str(e), LinstorManagerError.ERR_RESOURCE_GROUP_CREATE) from e
                        raise

            raise LinstorManagerError(
                f"Failed to create resource group `{group_name}`: "
                f"`{self._get_error_str(errors)}`.",
                LinstorManagerError.ERR_RESOURCE_GROUP_CREATE
            )

        # 2. Create volume group.
        errors = self._filter_errors(self._exec_query(linstor.Linstor.volume_group_create, group_name))
        if errors:
            with contextlib.suppress(Exception):
                # TODO: Expose empty groups to report them in case of destroy failure.
                self.destroy_resource_group(group_name)

            raise LinstorManagerError(
                f"Failed to create volume of resource group `{group_name}`: "
                f"`{self._get_error_str(errors)}`.",
                LinstorManagerError.ERR_RESOURCE_GROUP_CREATE
            )

    def destroy_resource_group(self, group_name: str) -> None:
        errors = []
        def destroy_impl() -> bool:
            nonlocal errors
            errors = self._filter_errors(self._exec_query(linstor.Linstor.resource_group_delete, group_name))
            if not errors:
                self.invalidate_resource_group_cache()
                return True

            return bool(self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_RSC_GRP, )))

        # Use a timeout to deal with LVM cleanup and stuff like that.
        if not wait_for_condition(destroy_impl, timeout=30, interval=1):
            raise LinstorManagerError(
                f"Failed to destroy resource group `{group_name}`: "
                f"`{self._get_error_str(errors)}`.",
                LinstorManagerError.ERR_RESOURCE_GROUP_DESTROY
            )

    def get_resource_group_stats(self, group_name: str) -> Optional[ResourceGroupStats]:
        resource_group = self._fetch_one_resource_group(group_name)
        if not resource_group:
            raise LinstorManagerError(
                f"Failed to get stats of resource group `{group_name}`: "
                f"`{self._ERR_MSG_RESOURCE_GROUP_NOT_EXISTS}`.",
                LinstorManagerError.ERR_RESOURCE_GROUP_NOT_EXISTS
            )

        free_size = -1
        capacity = -1

        name_to_storage_pools_stats = self.get_controller_storage_pool_stats()
        for storage_pool_name in resource_group.select_filter.storage_pool_list:
            storage_pool_stats = name_to_storage_pools_stats.get(storage_pool_name)
            if not storage_pool_stats:
                continue

            for node_storage_pool_stats in storage_pool_stats:
                if node_storage_pool_stats.free_size >= 0 and node_storage_pool_stats.capacity >= 0:
                    free_size += node_storage_pool_stats.free_size
                    capacity += node_storage_pool_stats.capacity

        virtual_capacity = 0
        for resource_definition in self._fetch_resource_definitions().values():
            if resource_definition.resource_group_name != group_name:
                continue

            for volume_definition in resource_definition.volume_definitions:
                size = volume_definition.size
                if size < 0:
                    log.warning(
                        "Invalid resource definition size detected on "
                        f"`{resource_definition.name}/{volume_definition.number}: {virtual_capacity}."
                    )

                virtual_capacity += size * 1024

        return self.ResourceGroupStats(group_name, free_size, capacity, virtual_capacity)

    def get_resource_group_place_count(self, group_name: str) -> int:
        resource_group = self._fetch_one_resource_group(group_name)
        if resource_group:
            return self._get_resource_group_place_count(resource_group)

        raise LinstorManagerError(
            f"Failed to get place count of resource group `{group_name}`: "
            f"`{self._ERR_MSG_RESOURCE_GROUP_NOT_EXISTS}`.",
            LinstorManagerError.ERR_RESOURCE_GROUP_NOT_EXISTS
        )

    # ----------------------------------
    # Resource definition helpers.
    # ----------------------------------

    def create_resource_definition(self, resource_name: str, group_name: str, size: int) -> None:
        errors = self._filter_errors(self._exec_query(
            linstor.Linstor.resource_group_spawn,
            rsc_grp_name=group_name,
            rsc_dfn_name=resource_name,
            vlm_sizes=[f"{size}B"],
            definitions_only=True
        ))
        if not errors:
            self.invalidate_resource_definition_cache()
            try:
                self._set_resource_definition_peer_slots(resource_name, self.MAX_PEERS)
            except LinstorManagerError as e:
                if e.flags & LinstorManagerError.ERR_NETWORK:
                    raise

                with contextlib.suppress(Exception):
                    # TODO: Expose resource def without resources to report them in case of destroy failure.
                    self.destroy_resource_definition(resource_name)
                raise

        def raise_error(reason: str, flags: int = 0) -> Never:
            raise LinstorManagerError(
                f"Failed to create resource definition `{resource_name}` on group `{group_name}`: `{reason}`.",
                LinstorManagerError.ERR_RESOURCE_DEFINITION_CREATE | flags
            )

        if self._find_error(errors, (linstor.consts.FAIL_EXISTS_RSC_DFN, )):
            raise_error(self._ERR_MSG_RESOURCE_DEFINITION_EXISTS, LinstorManagerError.ERR_RESOURCE_DEFINITION_EXISTS)
        if self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_RSC_GRP, )):
            raise_error(self._ERR_MSG_RESOURCE_GROUP_NOT_EXISTS, LinstorManagerError.ERR_RESOURCE_GROUP_NOT_EXISTS)
        raise_error(self._get_error_str(errors))

    def destroy_resource_definition(self, resource_name: str) -> None:
        errors = self._filter_errors(self._exec_query(linstor.Linstor.resource_dfn_delete, resource_name))
        if not errors:
            # Note: replicas are deleted, so we must refresh storage pool and resource cache too.
            self.invalidate_storage_pool_cache()
            self.invalidate_resource_definition_cache()
            self.invalidate_resource_cache()
            return

        if not self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_RSC_DFN, )):
            raise LinstorManagerError(
                f"Failed to destroy resource definition `{resource_name}`: "
                f"`{self._get_error_str(errors)}`.",
                LinstorManagerError.ERR_RESOURCE_DEFINITION_DESTROY
            )

    def get_resource_definition_default_place_count(self, resource_name: str) -> int:
        resource_definition = self._fetch_one_resource_definition(resource_name)
        resource_group = resource_definition and \
            self._fetch_one_resource_group(resource_definition.resource_group_name)

        if not resource_definition or not resource_group:
            # If we have the definition but not the resource group, there is a bug or race condition with another call.
            raise LinstorManagerError(
                f"Failed to get default place count of resource definition `{resource_name}`: "
                f"`{self._ERR_MSG_RESOURCE_DEFINITION_NOT_EXISTS}`.",
                LinstorManagerError.ERR_RESOURCE_DEFINITION_NOT_EXISTS
            )

        return self._get_resource_group_place_count(resource_group)

    def set_resource_definition_auto_promote_timeout(self, resource_name: str, timeout: int) -> None:
        # Define the blocking time of open calls when a DRBD is already open on another node.
        self._set_resource_definition_properties(resource_name, {
            "DrbdOptions/Resource/auto-promote-timeout": timeout
        })

    def set_resource_definition_ha_mode(self, resource_name: str, *, enabled: bool) -> None:
        # Set or not HA DRBD properties required by drbd-reactor and by specific volumes.
        properties = {
            "DrbdOptions/auto-quorum": "disabled",
            "DrbdOptions/Resource/auto-promote": "no",
            "DrbdOptions/Resource/on-no-data-accessible": "io-error",
            "DrbdOptions/Resource/on-no-quorum": "io-error",
            "DrbdOptions/Resource/on-suspended-primary-outdated": "force-secondary",
            "DrbdOptions/Resource/quorum": "majority"
        }
        if enabled:
            self._set_resource_definition_properties(resource_name, properties)
        else:
            self._delete_resource_definition_properties(resource_name, list(properties.keys()))

    # ----------------------------------
    # Resource helpers.
    # ----------------------------------

    class ResourceMode(IntEnum):
        DISKLESS = 0
        DISKFUL = 1

    def create_resource(self, resource_name: str, node_name: str, mode: ResourceMode) -> None:
        self.create_resources(resource_name, { node_name: mode })

    def create_resources(self, resource_name: str, node_info: Dict[str, ResourceMode]) -> None:
        # If the requested resource does not exist on a node, then it is created as diskful or diskless.
        # Otherwise, if the resource is a tiebreaker, it's transformed into diskful or diskless.
        # If a resource is diskless, it can be promoted to diskful via this helper;
        # however, a diskful resource will remain diskful if a diskless resource is requested.
        if not node_info:
            return

        # Invalidate without waiting. This helper can create multiple resources,
        # we don't want to complicate error and cache management.
        self.invalidate_storage_pool_cache()
        self.invalidate_resource_cache()

        errors = self._filter_errors(self._exec_query(
            linstor.Linstor.resource_create,
            rscs=[
                linstor.ResourceData(
                    rsc_name=resource_name,
                    node_name=node_name,
                    diskless=(mode == LinstorManager.ResourceMode.DISKLESS)
                )
                for node_name, mode in node_info.items()
            ]
        ))
        if not errors:
            return

        # Important: the order of error checks is mandatory due to a Linstor API behavior/bug.
        # Context: python-linstor-1.23.0 / LINSTOR 1.29.2. This bug may be present in later versions.
        # The check `error.is_error(linstor.consts.FAIL_NOT_FOUND_NODE)` evaluates to True
        # even if the underlying error is actually `FAIL_NOT_FOUND_RSC_DFN` (likely due to bitmask overlap).
        # Therefore, we must explicitly check for `FAIL_NOT_FOUND_RSC_DFN` before checking for the node.
        #
        # Bug detected using:
        # print(f"ERROR CODE: {error.ret_code}")
        # print(f"TO TEST: {linstor.consts.FAIL_NOT_FOUND_RSC_DFN} {linstor.consts.FAIL_NOT_FOUND_NODE}")
        # print(f"RESULT: {error.is_error(linstor.consts.FAIL_NOT_FOUND_RSC_DFN)} {error.is_error(linstor.consts.FAIL_NOT_FOUND_NODE)}")
        #
        # Resource exists but node is missing:
        # ERROR CODE: -4611686018427387604
        # TO TEST: 13835058055282164013 13835058055282164012
        # RESULT: False True
        #
        # Node exists but resource is missing:
        # ERROR CODE: -4611686018407202515
        # TO TEST: 13835058055282164013 13835058055282164012
        # RESULT: True True

        def raise_error(reason: str, node_name: Optional[str] = None, flags: int = 0) -> Never:
            node_message = f" on node `{node_name}`" if node_name else ""
            raise LinstorManagerError(
                f"Failed to create resource `{resource_name}`{node_message}: `{reason}`.",
                LinstorManagerError.ERR_RESOURCE_CREATE | flags
            )

        if self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_RSC_DFN, )):
            raise_error(
                self._ERR_MSG_RESOURCE_DEFINITION_NOT_EXISTS,
                None,
                LinstorManagerError.ERR_RESOURCE_DEFINITION_NOT_EXISTS
            )

        error = self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_NODE, ))
        if error:
            raise_error(
                self._ERR_MSG_NODE_NOT_EXISTS,
                self._get_node_name_from_error(error),
                LinstorManagerError.ERR_NODE_NOT_EXISTS
            )

        raise_error(self._get_error_str(errors))

    def place_resource(self, resource_name: str, place_count: Optional[int] = None) -> None:
        error_flags = LinstorManagerError.ERR_RESOURCE_CREATE

        if not place_count:
            try:
                place_count = self.get_resource_definition_default_place_count(resource_name)
            except LinstorManagerError as e:
                if e.flags & LinstorManagerError.ERR_RESOURCE_DEFINITION_NOT_EXISTS:
                    raise LinstorManagerError(str(e), error_flags | e.flags) from e
                raise

        # Invalidate without waiting. This helper can create multiple resources,
        # we don't want to complicate error and cache management.
        self.invalidate_storage_pool_cache()
        self.invalidate_resource_cache()

        errors = self._filter_errors(self._exec_query(
            linstor.Linstor.resource_auto_place,
            rsc_name=resource_name,
            place_count=place_count,
            diskless_on_remaining=False
        ))
        if not errors:
            return

        def raise_error(reason: str, flags: int = 0) -> Never:
            raise LinstorManagerError(
                f"Failed to place resource `{resource_name}`: `{reason}`.",
                LinstorManagerError.ERR_RESOURCE_CREATE | flags
            )

        if self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_RSC_DFN, )):
            raise_error(
                self._ERR_MSG_RESOURCE_DEFINITION_NOT_EXISTS,
                LinstorManagerError.ERR_RESOURCE_DEFINITION_NOT_EXISTS
            )
        raise_error(self._get_error_str(errors))

    def destroy_resource(self, resource_name: str, node_name: str) -> None:
        errors = self._filter_errors(self._exec_query(
            linstor.Linstor.resource_delete,
            node_name=node_name,
            rsc_name=resource_name
        ))
        if not errors:
            # If node is missing, this branch is also executed.
            self.invalidate_storage_pool_cache()
            self.invalidate_resource_cache()
            return

        if not self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_RSC, )):
            raise LinstorManagerError(
                f"Failed to destroy resource `{resource_name}` on node `{node_name}`: "
                f"`{self._get_error_str(errors)}`.",
                LinstorManagerError.ERR_RESOURCE_DESTROY
            )

    def toggle_resource(self, resource_name: str, node_name: str, diskless: bool) -> None:
        self.invalidate_storage_pool_cache()
        self.invalidate_resource_cache()
        errors = self._filter_errors(self._exec_query(
            linstor.Linstor.resource_toggle_disk,
            node_name=node_name,
            rsc_name=resource_name,
            diskless=diskless
        ))
        if not errors:
            return

        def raise_error(reason: str, flags: int = 0) -> Never:
            state = "Diskless" if diskless else "Diskful"
            raise LinstorManagerError(
                f"Could not toggle resource `{resource_name}` on node `{node_name}` to {state}: `{reason}`.",
                LinstorManagerError.ERR_RESOURCE_TOGGLE | flags
            )

        if self._find_error(errors, linstor.consts.FAIL_NOT_FOUND_RSC_DFN):
            raise_error(
                self._ERR_MSG_RESOURCE_DEFINITION_NOT_EXISTS,
                LinstorManagerError.ERR_RESOURCE_DEFINITION_NOT_EXISTS
            )
        if self._find_error(errors, linstor.consts.FAIL_NOT_FOUND_NODE):
            raise_error(self._ERR_MSG_NODE_NOT_EXISTS, LinstorManagerError.ERR_NODE_NOT_EXISTS)
        raise_error(self._get_error_str(errors))

    def is_resource_path_available(self, resource_name: str, node_name: str) -> bool:
        resource_entry = self._fetch_one_resource_entry(resource_name)
        if not resource_entry:
            return False

        resource = next((resource for resource in resource_entry.resources if resource.node_name == node_name), None)
        if not resource:
            return False

        return self._is_active_resource(resource) and not self._is_tie_breaker_resource(resource)

    def get_resource_in_use_node_name(self, resource_name: str) -> str:
        resource_entry = self._fetch_one_resource_entry(resource_name)
        if not resource_entry:
            return ""

        resource_state = next(
            (resource_state for resource_state in resource_entry.states if resource_state.in_use),
            None
        )
        return resource_state.node_name if resource_state else ""

    def remove_resource_skip_disk_flag(self, resource_name: str, node_name: str) -> None:
        return self._delete_resource_properties(resource_name, node_name, ["DrbdOptions/SkipDisk"])

    def resources_evacuate(
        self, node_name: str, group_names: Optional[Set[str]] = None, keep_diskless: bool = True
    ) -> None:
        all_resource_replicas = self.get_controller_resource_replicas(
            group_names, {node_name}, self.ResourceReplicasMode.STRICT_DATA_INTEGRITY
        )
        if not all_resource_replicas:
            return

        name_to_storage_pools_stats = self.get_controller_storage_pool_stats()

        for resource_replicas in all_resource_replicas:
            # 1. Check if we must move this resource.
            is_diskless = node_name in resource_replicas.diskless_node_names
            if keep_diskless and is_diskless:
                continue

            is_diskful = node_name in resource_replicas.diskful_node_names
            if not is_diskful and not is_diskless:
                continue # No replica on node to evacuate.

            assert is_diskful and not is_diskless

            # 2. Compute how many diskful/replicas to create.
            expected_place_count = resource_replicas.expected_place_count
            resource_name = resource_replicas.name
            # Contains the number of replicas AFTER evacuate call.
            replica_count = resource_replicas.diskless_count + resource_replicas.diskful_count
            missing_diskful_count = expected_place_count - resource_replicas.diskful_count

            # A. No need for new diskful.
            if resource_replicas.diskful_count >= resource_replicas.place_count:
                if keep_diskless:
                else:
    def resources_remove_skip_disks(self) -> None:
        name_to_resources = self._fetch_resources()

        for resources in name_to_resources.values():
            skip_disk_resources = {
                resource.node_name: resource
                for resource in resources
                if self._is_skip_disk_resource(resource)
            }
            # Skip disk deletion is only permitted if at least one remaining volume is in a stable state.
            if not any(
                self._is_active_resource(resource) and all(map(resource.volumes, self._is_up_to_date_volume))
                for resource in resources
                if resource.node_name not in skip_disk_resources
                for volume in resource.volumes
            ):
                continue

            for resource in skip_disk_resources.values():
                try:
                    if linstor.consts.FLAG_DISKLESS not in resource.flags:
                        self.toggle_resource(resource.name, resource.node_name, True)
                    self.remove_resource_skip_disk_flag(resource.name, resource.node_name)
                except LinstorManagerError as e:
                    if e.code == LinstorManagerError.ERR_NETWORK:
                        raise
                    logger(
                        f"Failed to delete skip disk on resource `{resource.name}`"
                        f" on node `{resource.node_name}`: `{e}`."
                    )

    # ----------------------------------
    # Cache helpers.
    # ----------------------------------

    def invalidate_node_cache(self) -> None:
        self._fetch_nodes_impl.cache_clear()

    def invalidate_storage_pool_cache(self) -> None:
        self._fetch_storage_pools_impl.cache_clear()

    def invalidate_resource_group_cache(self) -> None:
        self._fetch_resource_groups_impl.cache_clear()

    def invalidate_resource_cache(self) -> None:
        self._fetch_resource_entries_impl.cache_clear()
        self._fetch_one_resource_entry.cache_clear()

    def invalidate_resource_definition_cache(self) -> None:
        self._fetch_resource_definitions_impl.cache_clear()
        self._fetch_one_resource_definition.cache_clear()

    # ----------------------------------
    # Fetch helpers.
    # ----------------------------------

    class ResourceEntry:
        def __init__(self) -> None:
            self.resources: List[linstor.responses.Resource] = []
            self.states: List[linstor.responses.ResourceState] = []

    @staticmethod
    def _sanitize_err_fetch_reason(reason: Any) -> str:
        # If we don't have a reason, there is probably a node version mismatch or something like that.
        return str(reason) if reason else "controller issue"

    @staticmethod
    def _fetch_filter(items: Dict[str, T], name_filter: Optional[Collection[str]]) -> Dict[str, T]:
        if not name_filter:
            return items
        return {
            key: value
            for key, value in items.items()
            if key in name_filter
        }

    def _fetch_nodes(
        self, name_filter: Optional[Set[str]] = None
    ) -> Dict[str, linstor.responses.Node]:
        return self._fetch_filter(self._fetch_nodes_impl(), name_filter)

    def _fetch_one_node(self, node_name: str) -> Optional[linstor.responses.Node]:
        return next(iter(self._fetch_nodes({node_name}).values()), None)

    @functools.lru_cache(maxsize=1)
    def _fetch_nodes_impl(self) -> Dict[str, linstor.responses.Node]:
        def raise_error(reason: str) -> Never:
            raise LinstorManagerError(
                f"Failed to fetch nodes: `{reason}`.",
                LinstorManagerError.ERR_NODE_FETCH
            )

        result = self._exec_query(linstor.Linstor.node_list)
        if not result:
            raise_error(self._ERR_MSG_NO_DATA)
        result = result[0]

        if not isinstance(result, linstor.responses.NodeListResponse):
            raise_error(self._sanitize_err_fetch_reason(result))

        return {node.name: node for node in result.nodes}

    def _fetch_storage_pools(
        self, name_filter: Optional[Set[str]] = None
    ) -> Dict[str, List[linstor.responses.StoragePool]]:
        return self._fetch_filter(self._fetch_storage_pools_impl(), name_filter)

    @functools.lru_cache(maxsize=1)
    def _fetch_storage_pools_impl(self) -> Dict[str, List[linstor.responses.StoragePool]]:
        def raise_error(reason: str) -> Never:
            raise LinstorManagerError(
                f"Failed to fetch storage pools: `{reason}`.",
                LinstorManagerError.ERR_STORAGE_POOL_FETCH
            )

        result = self._exec_query(linstor.Linstor.storage_pool_list)
        if not result:
            raise_error(self._ERR_MSG_NO_DATA)
        result = result[0]

        if not isinstance(result, linstor.responses.StoragePoolListResponse):
            raise_error(self._sanitize_err_fetch_reason(result))

        storage_pools = defaultdict(list)
        for storage_pool in result.storage_pools:
            storage_pools[storage_pool.name].append(storage_pool)
        return storage_pools

    def _fetch_resource_groups(
        self, name_filter: Optional[Set[str]] = None
    ) -> Dict[str, linstor.responses.ResourceGroup]:
        return self._fetch_filter(self._fetch_resource_groups_impl(), name_filter)

    def _fetch_one_resource_group(self, group_name: str) -> Optional[linstor.responses.ResourceGroup]:
        return next(iter(self._fetch_resource_groups({group_name}).values()), None)

    @functools.lru_cache(maxsize=1)
    def _fetch_resource_groups_impl(self) -> Dict[str, linstor.responses.ResourceGroup]:
        # There is no `resource_group_list` method, so find LINSTOR API call exception...
        try:
            result = self._exec_query(linstor.Linstor.resource_group_list_raise)
        except Exception as e:
            cause = e.__cause__
            if not cause:
                raise
            raise LinstorManagerError(
                f"Failed to fetch resource groups: `{cause}`.",
                LinstorManagerError.ERR_RESOURCE_GROUP_FETCH
            ) from None

        return {resource_group.name: resource_group for resource_group in result.resource_groups}

    def _fetch_resource_definitions(
        self, name_filter: Optional[Set[str]] = None
    ) -> Dict[str, linstor.responses.ResourceDefinition]:
        if not name_filter or len(name_filter) > 64 or self._fetch_resource_definitions_impl.cache_info().currsize:
            return self._fetch_resource_definitions_impl(tuple(name_filter) if name_filter else ())

        resource_definitions = {}
        for resource_name in name_filter:
            resource_definition = self._fetch_one_resource_definition(resource_name)
            if resource_definition:
                resource_definitions[resource_name] = resource_definition
        return resource_definitions

    @functools.lru_cache(maxsize=128)
    def _fetch_one_resource_definition(self, resource_name: str) -> Optional[linstor.responses.ResourceDefinition]:
        return next(iter(self._fetch_resource_definitions_uncached((resource_name, )).values()), None)

    @functools.lru_cache(maxsize=1)
    def _fetch_resource_definitions_impl(
        self, name_filter: Tuple[str, ...]
    ) -> Dict[str, linstor.responses.ResourceDefinition]:
        return self._fetch_filter(self._fetch_resource_definitions_uncached(()), name_filter)

    def _fetch_resource_definitions_uncached(
        self, name_filter: Tuple[str, ...]
    ) -> Dict[str, linstor.responses.ResourceDefinition]:
        def raise_error(reason: str) -> Never:
            raise LinstorManagerError(
                f"Failed to fetch resource definitions: `{reason}`.",
                LinstorManagerError.ERR_RESOURCE_DEFINITION_FETCH
            )

        result = self._exec_query(
            linstor.Linstor.resource_dfn_list,
            query_volume_definitions=True,
            filter_by_resource_definitions=name_filter
        )
        if not result:
            raise_error(self._ERR_MSG_NO_DATA)
        result = result[0]

        if not isinstance(result, linstor.responses.ResourceDefinitionResponse):
            raise_error(self._sanitize_err_fetch_reason(result))

        return {resource_definition.name: resource_definition for resource_definition in result.resource_definitions}

    def _fetch_resource_entries(self, name_filter: Optional[Set[str]] = None) -> Dict[str, ResourceEntry]:
        if not name_filter or len(name_filter) > 64 or self._fetch_resource_entries_impl.cache_info().currsize:
            return self._fetch_resource_entries_impl(tuple(name_filter) if name_filter else ())

        resource_entries = {}
        for resource_name in name_filter:
            resource_entry = self._fetch_one_resource_entry(resource_name)
            if resource_entry:
                resource_entries[resource_name] = resource_entry
        return resource_entries

    @functools.lru_cache(maxsize=128)
    def _fetch_one_resource_entry(self, resource_name: str) -> Optional[ResourceEntry]:
        return next(iter(self._fetch_resource_entries_uncached((resource_name, )).values()), None)

    @functools.lru_cache(maxsize=1)
    def _fetch_resource_entries_impl(self, name_filter: Tuple[str, ...]) -> Dict[str, ResourceEntry]:
        return self._fetch_filter(self._fetch_resource_entries_uncached(()), name_filter)

    def _fetch_resource_entries_uncached(self, name_filter: Tuple[str, ...]) -> Dict[str, ResourceEntry]:
        def raise_error(reason: str) -> Never:
            raise LinstorManagerError(
                f"Failed to fetch resources: `{reason}`.",
                LinstorManagerError.ERR_RESOURCE_FETCH
            )

        result = self._exec_query(linstor.Linstor.resource_list, filter_by_resources=name_filter)
        if not result:
            raise_error(self._ERR_MSG_NO_DATA)
        result = result[0]

        if not isinstance(result, linstor.responses.ResourceResponse):
            raise_error(self._sanitize_err_fetch_reason(result))

        resource_entries: Dict[str, self.ResourceEntry] = defaultdict(self.ResourceEntry)

        for resource in result.resources:
            resource_entries[resource.name].resources.append(resource)
        for resource_state in result.resource_states:
            resource_entries[resource_state.name].states.append(resource_state)

        return resource_entries

    # ----------------------------------
    # Node helpers impl.
    # ----------------------------------

    @staticmethod
    def _get_node_name_from_error(error: linstor.responses.ApiCallResponse) -> str:
        object_refs = error.object_refs
        if object_refs:
            node_name = object_refs.get("Node")
            if node_name:
                return node_name

        for message in (error.message, error.details):
            if message:
                match = re.search(r"Node(?:\(s\):)? '([^']+)'", message)
                if match:
                    return match.group(1)

        return ""

    # ----------------------------------
    # Resource group helpers impl.
    # ----------------------------------

    @classmethod
    def _get_resource_group_place_count(cls, resource_group: linstor.responses.ResourceGroup) -> int:
        return resource_group.select_filter.place_count or cls.DEFAULT_PLACE_COUNT

    # ----------------------------------
    # Resource definition helpers impl.
    # ----------------------------------

    def _set_resource_definition_properties(self, resource_name: str, properties: Dict[str, Any]) -> None:
        self.invalidate_resource_definition_cache()
        errors = self._filter_errors(self._exec_query(
            linstor.Linstor.resource_dfn_modify,
            resource_name,
            property_dict=properties,
            delete_props=None
        ))
        if not errors:
            return

        def raise_error(reason: str, flags: int = 0) -> Never:
            raise LinstorManagerError(
                f"Failed to set resource definition properties of `{resource_name}`: `{reason}`.",
                LinstorManagerError.ERR_RESOURCE_DEFINITION_PROP_UPDATE | flags
            )

        if self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_RSC_DFN, )):
            raise_error(
                self._ERR_MSG_RESOURCE_DEFINITION_NOT_EXISTS,
                LinstorManagerError.ERR_RESOURCE_DEFINITION_NOT_EXISTS
            )
        raise_error(self._get_error_str(errors))

    def _delete_resource_definition_properties(self, resource_name: str, properties: List[str]) -> None:
        self.invalidate_resource_definition_cache()
        errors = self._filter_errors(self._exec_query(
            linstor.Linstor.resource_dfn_modify,
            resource_name,
            property_dict=None,
            delete_props=properties
        ))
        if not errors:
            return

        def raise_error(reason: str, flags: int = 0) -> Never:
            raise LinstorManagerError(
                f"Failed to delete resource definition properties of `{resource_name}`: `{reason}`.",
                LinstorManagerError.ERR_RESOURCE_DEFINITION_PROP_UPDATE | flags
            )

        if self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_RSC_DFN, )):
            raise_error(
                self._ERR_MSG_RESOURCE_DEFINITION_NOT_EXISTS,
                LinstorManagerError.ERR_RESOURCE_DEFINITION_NOT_EXISTS
            )
        raise_error(self._get_error_str(errors))

    def _set_resource_definition_peer_slots(self, resource_name: str, peer_slots: int) -> None:
        self.invalidate_resource_definition_cache()
        errors = self._filter_errors(self._exec_query(
            linstor.Linstor.resource_dfn_modify,
            name=resource_name,
            property_dict=None,
            delete_props=None,
            peer_slots=peer_slots
        ))
        if errors:
            raise LinstorManagerError(
                f"Failed to set resource definition peer slots of `{resource_name}`: "
                f"`{self._get_error_str(errors)}`.",
                # Use `create` error because this method must be called after definition creation.
                LinstorManagerError.ERR_RESOURCE_DEFINITION_CREATE
            )

    # ----------------------------------
    # Resource helpers impl.
    # ----------------------------------

    def _delete_resource_properties(self, resource_name: str, node_name: str, properties: List[str]) -> None:
        self.invalidate_resource_cache()
        errors = self._filter_errors(self._exec_query(
            linstor.Linstor.resource_modify,
            node_name=node_name,
            rsc_name=resource_name,
            property_dict=None,
            delete_props=properties
        ))
        if not errors:
            return

        def raise_error(reason: str, flags: int = 0) -> Never:
            raise LinstorManagerError(
                f"Failed to delete resource properties of `{resource_name}` on node `{node_name}`: `{reason}`.",
                LinstorManagerError.ERR_RESOURCE_PROP_UPDATE | flags
            )

        if self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_RSC_DFN, )):
            raise_error(
                self._ERR_MSG_RESOURCE_DEFINITION_NOT_EXISTS,
                LinstorManagerError.ERR_RESOURCE_DEFINITION_NOT_EXISTS
            )
        if self._find_error(errors, (linstor.consts.FAIL_NOT_FOUND_NODE, )):
            raise_error(self._ERR_MSG_NODE_NOT_EXISTS, LinstorManagerError.ERR_NODE_NOT_EXISTS)
        raise_error(self._get_error_str(errors))

    # ----------------------------------
    # `is`/`as` helpers.
    # ----------------------------------

    @staticmethod
    def _is_evacuating_node(node: linstor.responses.Node) -> bool:
        return linstor.consts.FLAG_EVACUATE in node.flags

    @staticmethod
    def _has_resource_flags(
        resource: Union[linstor.responses.Resource, linstor.responses.ResourceDefinition],
        flags: Tuple[str, ...]
    ) -> bool:
        return any(flag in resource.flags for flag in flags)

    @classmethod
    def _is_diskless_resource(cls, resource: linstor.responses.Resource) -> bool:
        return linstor.consts.FLAG_DISKLESS in resource.flags

    @classmethod
    def _is_tie_breaker_resource(cls, resource: linstor.responses.Resource) -> bool:
        return linstor.consts.FLAG_TIE_BREAKER in resource.flags

    @classmethod
    def _is_deleting_resource(
        cls, resource: Union[linstor.responses.Resource, linstor.responses.ResourceDefinition]
    ) -> bool:
        return cls._has_resource_flags(resource, (
            linstor.consts.FLAG_DELETE,
            linstor.consts.FLAG_DRBD_DELETE
        ))

    @staticmethod
    def _is_evacuating_resource(resource: linstor.responses.Resource) -> bool:
        return linstor.consts.FLAG_EVACUATE in resource.flags

    @staticmethod
    def _is_skip_disk_resource(resource: linstor.responses.Resource) -> bool:
        return resource.properties.get("DrbdOptions/SkipDisk") == "True"

    @classmethod
    def _is_active_resource(cls, resource: linstor.responses.Resource) -> bool:
        return not cls._is_deleting_resource(resource) and not cls._is_evacuating_resource(resource)

    @classmethod
    def _is_placed_resource(cls, resource: linstor.responses.Resource) -> bool:
        return cls._is_active_resource(resource) and not cls._is_skip_disk_resource(resource)

    @classmethod
    def _is_up_to_date_resource(cls, resource: linstor.responses.Resource) -> bool:
        return cls._is_placed_resource(resource) and all(map(cls._is_up_to_date_volume, resource.volumes))

    @staticmethod
    def _is_up_to_date_volume(volume: linstor.responses.Volume) -> bool:
        return volume.state.disk_state == "UpToDate"

# ==============================================================================

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("-u", "--uri", required=False)

    parser.add_argument("--create-missing-replicas", action="store_true")
    parser.add_argument("--remove-skip-disks", action="store_true")
    parser.add_argument("--evacuate-resources", action="store_true")

    args = parser.parse_args()

    linstor_manager = LinstorManager(args.uri)
    if args.remove_skip_disks:
        linstor_manager.resources_remove_skip_disks()
    if args.create_missing_replicas:
        linstor_manager.resources_create_missing_replicas()
    if args.evacuate_resources:
        linstor_manager.resources_evacuate()

if __name__ == "__main__":
    main()
