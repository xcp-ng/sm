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

import ssl

from xcp_storage.utils.json import JsonDict, JsonList
from xcp_storage.utils.json.rpc import JsonRpcRequestError
from xcp_storage.utils.json.rpc.client import (
    JSON_RPC_CLIENT_TIMEOUT,
    JSON_RPC_DEFAULT_TIMEOUT,
    JsonRpcClient,
)

from xcp_storage.typing import (
    Any,
    Callable,
    cast,
    Optional,
    ParamSpec,
    TypeVar,
    Union,
)

P = ParamSpec("P")
JsonValueT = TypeVar(
    "JsonValueT",
    # TODO: Should be uncommented once mypy/python better supports recursive types.
    # bound=JsonValue
)

# ==============================================================================

class RpcApiClient(JsonRpcClient):
    def __init__(
        self,
        address: str,
        port: int,
        ssl_context: Optional[ssl.SSLContext] = None,
        client_timeout: float = JSON_RPC_CLIENT_TIMEOUT
    ) -> None:
        super().__init__(address, port, ssl_context, client_timeout)

    def call_api(
        self,
        method: Callable[P, JsonValueT],
        *args: P.args,
        **kwargs: P.kwargs
    ) -> JsonValueT:
        return self.call_api_with_timeout(JSON_RPC_DEFAULT_TIMEOUT, method, *args, **kwargs)

    def call_api_with_timeout(
        self,
        timeout: float,
        method: Callable[P, JsonValueT],
        *args: P.args,
        **kwargs: P.kwargs
    ) -> JsonValueT:
        try:
            method_name = cast(Any, method)._rpc_name # noqa: SLF001
        except AttributeError:
            raise JsonRpcRequestError("Method is not marked as RPC.") from None

        if args and kwargs:
            raise JsonRpcRequestError("Positional and named arguments cannot be mixed.")

        params: Union[JsonList, JsonDict, None]
        if kwargs:
            params = cast(JsonDict, kwargs)
        elif args:
            params = cast(JsonList, list(args))
        else:
            params = None

        return cast(JsonValueT, self.call_with_timeout(timeout, method_name, params))
