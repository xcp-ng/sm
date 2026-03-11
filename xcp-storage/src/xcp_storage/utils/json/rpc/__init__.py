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
import contextlib
import inspect
import json
from pathlib import PurePath

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

class JsonRpcResponseError(JsonRpcError):
    def __init__(self, code: int, message: str, data: JsonValue = None) -> None:
        super().__init__(message)
        self._payload: Optional[JsonDict] = None
        self.code = code
        self.message = message
        self.data = data

    @property
    def payload(self) -> JsonDict:
        if self._payload is None:
            self._payload = {
                "code": self.code,
                "message": self.message
            }
            if self.data:
                self._payload["data"] = self.data
        return self._payload

    @classmethod
    def from_payload(cls, payload: JsonValue) -> "JsonRpcResponseError":
        if not isinstance(payload, dict):
            raise JsonRpcResponseClientError("Invalid response error, not a dict.")

        try:
            code = payload["code"]
            if not isinstance(code, int):
                raise JsonRpcResponseClientError("Invalid response error. `code` is not an integer.")

            message = payload["message"]
            if not isinstance(message, str):
                raise JsonRpcResponseClientError("Invalid response error. `message` is not a string.")

            data = payload.get("data")
        except KeyError as e:
            raise JsonRpcResponseClientError(f"Invalid response error. Missing member: `{e}`.") from None

        error_type = _CODE_TO_ERROR_TYPE.get(code)
        if not error_type:
            return JsonRpcResponseError(code, message, data)

        error = error_type(data)
        error.message = message
        return error

# ------------------------------------------------------------------------------

class JsonRpcResponseParseError(JsonRpcResponseError):
    def __init__(self, data: JsonValue = None) -> None:
        super().__init__(-32700, "Parse error", data)

class JsonRpcResponseInvalidRequestError(JsonRpcResponseError):
    def __init__(self, data: JsonValue = None) -> None:
        super().__init__(-32600, "Invalid Request", data)

class JsonRpcResponseMethodNotFoundError(JsonRpcResponseError):
    def __init__(self, data: JsonValue = None) -> None:
        super().__init__(-32601, "Method not found", data)

class JsonRpcResponseInvalidParamsError(JsonRpcResponseError):
    def __init__(self, data: JsonValue = None) -> None:
        super().__init__(-32602, "Invalid params", data)

class JsonRpcResponseInternalError(JsonRpcResponseError):
    def __init__(self, data: JsonValue = None) -> None:
        super().__init__(-32603, "Internal error", data)

class JsonRpcResponseServerError(JsonRpcResponseError):
    def __init__(self, data: JsonValue = None) -> None:
        super().__init__(-32000, "Server error", data)

# ------------------------------------------------------------------------------

class JsonRpcResponseClientError(JsonRpcResponseError):
    def __init__(self, message: str) -> None:
        super().__init__(-33000, message)

# ------------------------------------------------------------------------------

_CODE_TO_ERROR_TYPE = {
  -32700: JsonRpcResponseParseError,
  -32600: JsonRpcResponseInvalidRequestError,
  -32601: JsonRpcResponseMethodNotFoundError,
  -32602: JsonRpcResponseInvalidParamsError,
  -32603: JsonRpcResponseInternalError,
  -32000: JsonRpcResponseServerError
}

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
        self._json_payload: Optional[str] = None
        self.identifier = identifier
        self.method = method
        self.params = params

    def _invalidate(self) -> None:
        self._modified = True
        self._json_payload = None

    @property
    def identifier(self) -> Union[str, int, None]:
        return self._identifier

    @identifier.setter
    def identifier(self, value: Union[str, int, None]) -> None:
        self._identifier = value
        self._invalidate()

    @property
    def method(self) -> str:
        return self._method

    @method.setter
    def method(self, value: str) -> None:
        if value.startswith("rpc."):
            raise JsonRpcRequestError("Cannot use reserved RPC prefix as method name.")
        self._method = value
        self._invalidate()

    @property
    def params(self) -> Union[JsonList, JsonDict, None]:
        return self._params

    @params.setter
    def params(self, value: Union[JsonList, JsonDict, None]) -> None:
        self._params = value
        self._invalidate()

    @property
    def args(self) -> List:
        return self._params if isinstance(self._params, list) else []

    @args.setter
    def args(self, value: List[JsonValue]) -> None:
        self._params = value
        self._invalidate()

    @property
    def kwargs(self) -> JsonDict:
        return self._params if isinstance(self._params, dict) else {}

    @kwargs.setter
    def kwargs(self, value: JsonDict) -> None:
        self._params = value
        self._invalidate()

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
        if self._json_payload is None:
            self._json_payload = json.dumps(self.payload)
        return self._json_payload

    @classmethod
    def from_json(cls, request_str: str) -> Union["JsonRpcRequest", "JsonRpcBatchRequest"]:
        try:
            payload = json.loads(request_str)
        except (TypeError, ValueError):
            raise JsonRpcRequestError("Invalid request. Parse error.") from None
        return cls.from_payload(payload)

    @classmethod
    def from_payload(cls, payload: JsonValue) -> Union["JsonRpcRequest", "JsonRpcBatchRequest"]:
        if not isinstance(payload, list):
            return cls._from_request_payload(payload)

        if not payload:
            raise JsonRpcRequestError("Invalid request. Empty batch.")

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
            identifier = payload.get("id")
            if identifier is not None and not isinstance(identifier, (int, str)):
                raise JsonRpcRequestError("Invalid request. `id` is not an integer or string.")

            method = payload["method"]
            if not isinstance(method, str):
                raise JsonRpcRequestError("Invalid request. `method` is not a string.")

            params = payload.get("params")
            if params is not None and not isinstance(params, (list, dict)):
                raise JsonRpcRequestError("Invalid request. `params` is not a list or dict.")

            request.identifier = identifier
            request.method = method
            request.params = params
        except KeyError as e:
            raise JsonRpcRequestError(f"Invalid request. Missing member: `{e}`.") from None

        request._modified = False
        request._payload = payload

        return request

class JsonRpcBatchRequest(JsonRpcObject):
    def __init__(self, requests: List[JsonRpcRequest]) -> None:
        self.requests = requests

    @override
    def to_json(self) -> str:
        return "[" + ", ".join([request.to_json() for request in self.requests]) + "]"

# ------------------------------------------------------------------------------
# Response.
# ------------------------------------------------------------------------------

class JsonRpcResponse(JsonRpcObject):
    def __init__(
        self,
        *,
        identifier: Union[str, int, None] = None,
        error: Optional[JsonDict] = None,
        result: Any = None # noqa: ANN401
    ) -> None:
        if error is not None and result is not None:
            raise JsonRpcResponseClientError("Invalid response. Only error or result can be set, but not both.")

        self._payload: JsonDict = {}
        self._json_payload: Optional[str] = None
        self.identifier = identifier
        self.error = error
        self.result = result

    def _invalidate(self) -> None:
        self._modified = True
        self._json_payload = None

    @property
    def identifier(self) -> Union[str, int, None]:
        return self._identifier

    @identifier.setter
    def identifier(self, value: Union[str, int, None]) -> None:
        self._identifier = value
        self._invalidate()

    @property
    def error(self) -> Optional[JsonDict]:
        return self._error

    @error.setter
    def error(self, value: Optional[JsonDict]) -> None:
        if value is not None:
            try:
                _code = value["code"]
                _message = value["message"]
            except KeyError as e:
                raise JsonRpcResponseClientError(f"Invalid response. Missing error member: `{e}`.") from None

        self._error = value
        self._invalidate()

    @property
    def result(self) -> Any: # noqa: ANN401
        return self._result

    @result.setter
    def result(self, value: Any) -> None: # noqa: ANN401
        self._result = value
        self._invalidate()

    @property
    def payload(self) -> JsonDict:
        if not self._modified:
            return self._payload

        self._payload = {
            "jsonrpc": JSON_RPC_VERSION,
            "id": self._identifier
        }
        if self._error:
            self._payload["error"] = self._error
        else:
            self._payload["result"] = self._result

        self._modified = False
        return self._payload

    @override
    def to_json(self) -> str:
        if self._json_payload is None:
            self._json_payload = json.dumps(self.payload)
        return self._json_payload

    @classmethod
    def from_json(cls, response_str: str) -> Union["JsonRpcResponse", "JsonRpcBatchResponse"]:
        try:
            payload = json.loads(response_str)
        except (TypeError, ValueError):
            raise JsonRpcResponseClientError("Invalid reponse. Parse error.") from None
        return cls.from_payload(payload)

    @classmethod
    def from_payload(cls, payload: JsonValue) -> Union["JsonRpcResponse", "JsonRpcBatchResponse"]:
        if not isinstance(payload, list):
            return cls._from_response_payload(payload)

        if not payload:
            raise JsonRpcResponseClientError("Invalid reponse. Empty batch.")

        payloads = payload
        return JsonRpcBatchResponse([cls._from_response_payload(payload) for payload in payloads])

    @classmethod
    def _from_response_payload(cls, payload: JsonValue) -> "JsonRpcResponse":
        if not isinstance(payload, dict):
            raise JsonRpcResponseClientError("Invalid response. Payload must be an object or a list of objects.")

        payload = cast(JsonDict, payload)

        response = JsonRpcResponse()

        try:
            identifier = payload["id"]
            if identifier is not None and not isinstance(identifier, (int, str)):
                raise JsonRpcResponseClientError("Invalid response. `id` is not an integer or string.")

            error: JsonValue = None
            result: Any = None
            has_result = False

            with contextlib.suppress(KeyError):
                error = payload["error"]
                if not isinstance(error, dict):
                    raise JsonRpcResponseClientError("Invalid response. `error` is not an object.")

            with contextlib.suppress(KeyError):
                # We don't use `get` here to differentiate between: `"result": None` and the absence of field.
                result = payload["result"]
                has_result = True
                if error is not None:
                    raise JsonRpcResponseClientError("Invalid response. `error` and `result` are set.")

            if error is None and not has_result:
                raise JsonRpcResponseClientError("Invalid response. `error` and `result` are not set.")

            response.identifier = identifier
            response.error = cast(JsonDict, error)
            response.result = result
        except KeyError as e:
            raise JsonRpcResponseClientError(f"Invalid response. Missing member: `{e}`.") from None

        response._modified = False
        response._payload = payload

        return response

class JsonRpcBatchResponse(JsonRpcObject):
    def __init__(self, responses: List[JsonRpcResponse]) -> None:
        assert responses, "Response list must have at least one item."
        self.responses = responses

    @override
    def to_json(self) -> str:
        return "[" + ", ".join([response.to_json() for response in self.responses]) + "]"

# ------------------------------------------------------------------------------
# Dispatcher.
# ------------------------------------------------------------------------------

JsonRpcCallable = Callable[..., Any]

class JsonRpcCallResult:
    def __init__(self, *, result: Any = None, error: Optional[JsonRpcResponseError] = None) -> None: # noqa: ANN401
        assert error is None or result is None, "Only error or result can be set, but not both."
        self.result = result
        self.error = error

    def is_success(self) -> bool:
        return self.error is None

class JsonRpcDispatcher:
    def __init__(self, *, use_module_name: bool = False) -> None:
        self._name_to_method: Dict[str, JsonRpcCallable] = {}
        self._use_module_name = use_module_name

    def call_method(self, method: str, *args: Any, **kwargs: Any) -> Any: # noqa: ANN401
        try:
            target = self._name_to_method[method]
        except KeyError:
            return JsonRpcCallResult(error=JsonRpcResponseMethodNotFoundError())

        try:
            result = target(*args, **kwargs)
        except Exception as e:
            data: JsonDict = {"message": stringify_exception(e)}

            if isinstance(e, TypeError) and not is_callable_with(target, *args, **kwargs):
                return JsonRpcCallResult(error=JsonRpcResponseInvalidParamsError(data=data))
            return JsonRpcCallResult(error=JsonRpcResponseServerError(data=data))

        return JsonRpcCallResult(result=result)

    def method(self, func: Callable[P, T]) -> Callable[P, T]:
        name = func.__name__
        if self._use_module_name:
            name = PurePath(inspect.getfile(func)).stem + "." + name
        self._name_to_method[name] = func

        cast(Any, func)._rpc_name = name # noqa: SLF001
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
            return JsonRpcBatchResponse(responses)
        return None

    def _process_request(self, request: JsonRpcRequest) -> Optional[JsonRpcResponse]:
        identifier = request.identifier
        try:
            call_result = self._dispatcher.call_method(request.method, *request.args, **request.kwargs)
        except Exception as e:
            return JsonRpcResponse(
                identifier=identifier,
                error=JsonRpcResponseInternalError(data={
                    "message": stringify_exception(e)
                }).payload
            )

        if not call_result.is_success():
            return JsonRpcResponse(identifier=identifier, error=call_result.error.payload)

        if identifier is None:
            return None # Notification.

        response = JsonRpcResponse(identifier=identifier, result=call_result.result)
        try:
            response.to_json()
        except Exception as e:
            # It's possible that the value cannot be converted to JSON...
            return JsonRpcResponse(
                identifier=identifier,
                error=JsonRpcResponseServerError(data={
                    "message": stringify_exception(e)
                }).payload)
        return response

    def _process_requests(self, requests: List[JsonRpcRequest]) -> List[JsonRpcResponse]:
        responses = []
        for request in requests:
            response = self._process_request(request)
            if response:
                responses.append(response)
        return responses
