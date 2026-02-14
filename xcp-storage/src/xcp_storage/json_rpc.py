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

from abc import ABC, abstractmethod
import json

from xcp_storage.utils.exception import stringify_exception
from xcp_storage.utils.json import JsonDict, JsonList, JsonValue
from xcp_storage.utils.reflection import is_callable_with

from xcp_storage.typing import (
    Any,
    Callable,
    cast,
    Dict,
    List,
    Optional,
    override,
    ParamSpec,
    TypeVar,
    Union,
)

P = ParamSpec("P")
T = TypeVar("T")

# ==============================================================================

JSON_RPC_VERSION = "2.0"

# ------------------------------------------------------------------------------
# Base error.
# ------------------------------------------------------------------------------

class JsonRpcError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)

# ------------------------------------------------------------------------------
# Request errors.
# ------------------------------------------------------------------------------

class JsonRpcRequestError(JsonRpcError):
    pass

# ------------------------------------------------------------------------------
# Response errors.
# ------------------------------------------------------------------------------

class _JsonRpcResponseError(JsonRpcError):
    def __init__(self, data: Optional[JsonDict] = None) -> None:
        super().__init__(self.MESSAGE)
        self.payload = {
            "code": self.CODE,
            "message": self.MESSAGE
        }
        if data:
            self.payload["data"] = data
        self.data = data

# ------------------------------------------------------------------------------

class JsonRpcResponseParseError(_JsonRpcResponseError):
    CODE = -32700
    MESSAGE = "Parse error"

class JsonRpcResponseInvalidRequestError(_JsonRpcResponseError):
    CODE = -32600
    MESSAGE = "Invalid Request"

class JsonRpcResponseMethodNotFoundError(_JsonRpcResponseError):
    CODE = -32601
    MESSAGE = "Method not found"

class JsonRpcResponseInvalidParamsError(_JsonRpcResponseError):
    CODE = -32602
    MESSAGE = "Invalid params"

class JsonRpcResponseInternalError(_JsonRpcResponseError):
    CODE = -32603
    MESSAGE = "Internal error"

class JsonRpcResponseServerError(_JsonRpcResponseError):
    CODE = -32000
    MESSAGE = "Server error"

# ------------------------------------------------------------------------------
# Base Response/Request object.
# ------------------------------------------------------------------------------

class JsonRpcObject(ABC):
    @abstractmethod
    def to_json(self) -> str:
        pass

# ------------------------------------------------------------------------------
# Request.
# ------------------------------------------------------------------------------

class JsonRpcRequest(JsonRpcObject):
    PAYLOAD_MEMBERS = {"jsonrpc", "method", "params", "id"}
    PAYLOAD_REQUIRED_MEMBERS = {"jsonrpc", "method"}

    def __init__(
        self,
        identifier: Union[str, int, None] = None,
        method: str = "",
        params: Union[JsonList, JsonDict, None] = None
    ) -> None:
        self._payload: JsonDict = {}
        self._modified = True
        self.identifier = identifier
        self.method = method
        self.params = params

    @property
    def identifier(self) -> Union[str, int, None]:
        return self._identifier

    @identifier.setter
    def identifier(self, value: Union[str, int, None]) -> None:
        self._identifier = value
        self._modified = True

    @property
    def method(self) -> str:
        return self._method

    @method.setter
    def method(self, value: str) -> None:
        if value.startswith("rpc."):
            raise JsonRpcRequestError("Cannot use reserved RPC prefix as method name.")
        self._method = value
        self._modified = True

    @property
    def params(self) -> Union[JsonList, JsonDict, None]:
        return self._params

    @params.setter
    def params(self, value: Union[JsonList, JsonDict, None]) -> None:
        self._params = value
        self._modified = True

    @property
    def args(self) -> List:
        return self._params if isinstance(self._params, list) else []

    @args.setter
    def args(self, value: List[JsonValue]) -> None:
        self._params = value
        self._modified = True

    @property
    def kwargs(self) -> JsonDict:
        return self._params if isinstance(self._params, dict) else {}

    @kwargs.setter
    def kwargs(self, value: JsonDict) -> None:
        self._params = value
        self._modified = True

    @property
    def payload(self) -> JsonDict:
        if not self._modified:
            return self._payload

        if not self._method:
            raise JsonRpcRequestError("Method is missing.")

        self._payload = {
            "jsonrpc": JSON_RPC_VERSION,
            "method": self._method
        }
        if self._params:
            self._payload["params"] = self._params
        if self._identifier:
            self._payload["id"] = self._identifier

        self._modified = False
        return self._payload

    @override
    def to_json(self) -> str:
        return json.dumps(self.payload)

    @classmethod
    def from_payload(cls, payload: JsonValue) -> Union["JsonRpcRequest", "JsonRpcBatchRequest"]:
        if not isinstance(payload, list):
            return cls._from_request_payload(payload)

        if not payload:
            raise JsonRpcRequestError("Invalid request: `empty batch`.")

        payloads = payload
        return JsonRpcBatchRequest([cls._from_request_payload(payload) for payload in payloads])

    @classmethod
    def _from_request_payload(cls, payload: JsonValue) -> "JsonRpcRequest":
        if not isinstance(payload, dict):
            raise JsonRpcRequestError("Invalid request. Payload must be an object or a list of objects.")

        payload = cast(JsonDict, payload)

        payload_keys = set(payload.keys())

        missing_members = cls.PAYLOAD_REQUIRED_MEMBERS - payload_keys
        unknown_members = payload_keys - cls.PAYLOAD_MEMBERS
        if missing_members or unknown_members:
            raise JsonRpcRequestError(
                f"Invalid request. Missing members: `{missing_members or '{}'}`, "
                f"unknown members: `{unknown_members or '{}'}`."
            )

        request = JsonRpcRequest()

        try:
            method = payload["method"]
            if not isinstance(method, str):
                raise JsonRpcRequestError("`method` is not a string.") from None
            params = payload.get("params")
            if params is not None and not isinstance(params, (list, dict)):
                raise JsonRpcRequestError("`params` is not a list or dict.") from None
            identifier = payload.get("id")
            if identifier is not None and not isinstance(identifier, (int, str)):
                raise JsonRpcRequestError("`id` is not a list or dict.") from None

            request.method = method
            request.params = params
            request.identifier = identifier
        except ValueError as e:
            raise JsonRpcRequestError(f"Missing member: `{e}`.") from None
        except Exception as e:
            raise JsonRpcRequestError(f"Unable to create request: `{e}`.") from None

        return request

class JsonRpcBatchRequest(JsonRpcObject):
    def __init__(self, requests: List[JsonRpcRequest]) -> None:
        self.requests = requests

    @override
    def to_json(self) -> str:
        return json.dumps([request.payload for request in self.requests])

# ------------------------------------------------------------------------------
# Response.
# ------------------------------------------------------------------------------

class JsonRpcResponse(JsonRpcObject):
    def __init__(
        self,
        *,
        request: Optional[JsonRpcRequest] = None,
        error: Optional[JsonDict] = None,
        result: Any = None # noqa: ANN401
    ) -> None:
        assert error is None or result is None, "Only error or result can be set, but not both."

        payload: JsonDict = {
            "jsonrpc": JSON_RPC_VERSION,
            "id": request.identifier if request else None
        }
        if error:
            payload["error"] = error
        else:
            payload["result"] = result

        # TODO: Detect a `to_json` method on `result` or use a specific encoder.
        self._json_payload = json.dumps(payload)

        self.request = request
        self.error = error
        self.result = result
        self.payload = payload

    @override
    def to_json(self) -> str:
        return self._json_payload

class JsonRpcBatchResponse(JsonRpcObject):
    def __init__(self, request: JsonRpcBatchRequest, responses: List[JsonRpcResponse]) -> None:
        assert responses, "Response list must have at least one item."
        self.request = request
        self.responses = responses

    @override
    def to_json(self) -> str:
        return "[" + ", ".join([response.to_json() for response in self.responses]) + "]"

# ------------------------------------------------------------------------------
# Dispatcher.
# ------------------------------------------------------------------------------

class JsonRpcCallResult:
    def __init__(self, *, result: Any = None, error: Optional[_JsonRpcResponseError] = None) -> None: # noqa: ANN401
        assert error is None or result is None, "Only error or result can be set, but not both."
        self.result = result
        self.error = error

    def is_success(self) -> bool:
        return self.error is None

class JsonRpcDispatcher:
    def __init__(self) -> None:
        self._name_to_method: Dict[str, Callable[..., Any]] = {}

    def call_method(self, method: str, *args: Any, **kwargs: Any) -> Any: # noqa: ANN401
        try:
            target = self._name_to_method[method]
        except KeyError:
            return JsonRpcCallResult(error=JsonRpcResponseMethodNotFoundError())

        try:
            result = target(*args, **kwargs)
        except Exception as e:
            data: JsonDict = {"message": stringify_exception(e)}

            # TODO: Use verify_call from pydantic to check JSON arguments.
            if isinstance(e, TypeError) and not is_callable_with(target, *args, **kwargs):
                return JsonRpcCallResult(error=JsonRpcResponseInvalidParamsError(data=data))
            else:
                return JsonRpcCallResult(error=JsonRpcResponseServerError(data=data))

        return JsonRpcCallResult(result=result)

    def method(self, func: Callable[P, T]) -> Callable[P, T]:
        self._name_to_method[func.__name__] = func
        return func

# ------------------------------------------------------------------------------
# Request processor.
# ------------------------------------------------------------------------------

class JsonRpcRequestProcessor:
    def __init__(self, dispatcher: JsonRpcDispatcher) -> None:
        self._dispatcher = dispatcher

    def process(self, request_str: str) -> Union[JsonRpcResponse, JsonRpcBatchResponse, None]:
        # 1. Get request payload.
        try:
            payload = json.loads(request_str)
        except (TypeError, ValueError):
            # Note: no type errors should occur if type checking is used,
            # but just in case, it's best to have it checked....
            return JsonRpcResponse(error=JsonRpcResponseParseError().payload)

        # 2. Get request.
        try:
            request = JsonRpcRequest.from_payload(payload)
        except JsonRpcRequestError as e:
            return JsonRpcResponse(
                error=JsonRpcResponseInvalidRequestError(data={
                    "message": stringify_exception(e)
                }).payload
            )

        # 3. Process request.
        if isinstance(request, JsonRpcRequest):
            return self._process_request(request)

        responses = self._process_requests(request.requests)
        if responses:
            return JsonRpcBatchResponse(request, responses)
        return None

    def _process_request(self, request: JsonRpcRequest) -> Optional[JsonRpcResponse]:
        try:
            call_result = self._dispatcher.call_method(request.method, *request.args, **request.kwargs)
        except Exception as e:
            return JsonRpcResponse(
                request=request,
                error=JsonRpcResponseInternalError(data={
                    "message": stringify_exception(e)
                }).payload
            )

        if not call_result.is_success():
            return JsonRpcResponse(request=request, error=call_result.error.payload)

        if request.identifier is None:
            return None # Notification.

        try:
            return JsonRpcResponse(request=request, result=call_result.result)
        except Exception as e:
            # Probably a problem with the conversion of the result to JSON.
            return JsonRpcResponse(
                request=request,
                error=JsonRpcResponseServerError(data={
                    "message": stringify_exception(e)
                }).payload)

    def _process_requests(self, requests: List[JsonRpcRequest]) -> List[JsonRpcResponse]:
        responses = []
        for request in requests:
            response = self._process_request(request)
            if response:
                responses.append(response)
        return responses
