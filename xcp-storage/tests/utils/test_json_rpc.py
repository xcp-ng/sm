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

from xcp_storage.utils.json import JsonDict, JsonValue
from xcp_storage.utils.json.rpc import (
    JSON_RPC_VERSION,
    JsonRpcBatchRequest,
    JsonRpcBatchResponse,
    JsonRpcDispatcher,
    JsonRpcRequest,
    JsonRpcRequestProcessor,
    JsonRpcResponse,
)

from xcp_storage.typing import Union

# ==============================================================================

def assert_response_result_impl(
    response: Union[JsonRpcResponse, JsonRpcBatchResponse],
    expected_identifier: Union[int, None],
    expected_result: JsonValue
) -> None:
    assert isinstance(response, JsonRpcResponse)

    payload = response.payload
    assert payload["jsonrpc"] == JSON_RPC_VERSION
    assert payload["id"] == expected_identifier
    assert payload["result"] == expected_result

def assert_response_result(
    response: Union[JsonRpcResponse, JsonRpcBatchResponse, None],
    expected_identifier: Union[int, None],
    expected_result: JsonValue
) -> None:
    assert isinstance(response, JsonRpcResponse)
    assert_response_result_impl(response, expected_identifier, expected_result)
    assert_response_result_impl(JsonRpcResponse.from_json(response.to_json()), expected_identifier, expected_result)

# ------------------------------------------------------------------------------

def assert_response_error_impl(
    response: Union[JsonRpcResponse, JsonRpcBatchResponse],
    expected_identifier: Union[int, None],
    expected_error: JsonDict
) -> None:
    assert isinstance(response, JsonRpcResponse)

    payload = response.payload
    assert payload["jsonrpc"] == JSON_RPC_VERSION
    assert payload["id"] == expected_identifier
    assert payload["error"] == expected_error

def assert_response_error(
    response: Union[JsonRpcResponse, JsonRpcBatchResponse, None],
    expected_identifier: Union[int, None],
    expected_error: JsonDict
) -> None:
    assert isinstance(response, JsonRpcResponse)
    assert_response_error_impl(response, expected_identifier, expected_error)
    assert_response_error_impl(JsonRpcResponse.from_json(response.to_json()), expected_identifier, expected_error)

# ------------------------------------------------------------------------------

class TestJsonRpcRequest:
    def test_positional_params(self) -> None:
        dispatcher = JsonRpcDispatcher()

        @dispatcher.method
        def substract(a: int, b: int) -> int:
            return a - b

        request_processor = JsonRpcRequestProcessor(dispatcher)
        request = JsonRpcRequest(1, "substract", [42, 23])
        response = request_processor.process(request.to_json())
        assert_response_result(response, 1, 19)

    def test_named_params(self) -> None:
        dispatcher = JsonRpcDispatcher()

        @dispatcher.method
        def substract(a: int, b: int) -> int:
            return a - b

        request_processor = JsonRpcRequestProcessor(dispatcher)
        request = JsonRpcRequest(2, "substract", {"a": 23, "b": 42})
        response = request_processor.process(request.to_json())
        assert_response_result(response, 2, -19)

    def test_notification(self) -> None:
        dispatcher = JsonRpcDispatcher()

        @dispatcher.method
        def hello(message: str) -> str:
            return message

        request_processor = JsonRpcRequestProcessor(dispatcher)
        request = JsonRpcRequest(None, "hello", {"message": "Hi!"})
        response = request_processor.process(request.to_json())
        assert response is None

    def test_parse_error(self) -> None:
        dispatcher = JsonRpcDispatcher()

        request_processor = JsonRpcRequestProcessor(dispatcher)
        response = request_processor.process('{"jsonrpc": "2.0", "method": "foobar, "params": "bar", "baz]')
        assert_response_error(response, None, {"code": -32700, "message": "Parse error"})

    def test_invalid_request(self) -> None:
        dispatcher = JsonRpcDispatcher()

        request_processor = JsonRpcRequestProcessor(dispatcher)
        response = request_processor.process('{"jsonrpc": "2.0", "method": 1, "params": "bar"}')
        assert_response_error(response, None, {
            "code": -32600,
            "message": "Invalid Request",
            "data": {"message": "Invalid request. `method` is not a string."}
        })

    def test_method_not_found(self) -> None:
        dispatcher = JsonRpcDispatcher()

        request = JsonRpcRequest(1, "foobar")
        request_processor = JsonRpcRequestProcessor(dispatcher)
        response = request_processor.process(request.to_json())
        assert_response_error(response, 1, {"code": -32601, "message": "Method not found"})

    def test_invalid_params(self) -> None:
        dispatcher = JsonRpcDispatcher()

        @dispatcher.method
        def multiply(a: int, b: int) -> int:
            return a * b

        request_processor = JsonRpcRequestProcessor(dispatcher)
        request = JsonRpcRequest(1, "multiply", {"a": 23, "c": 42})
        response = request_processor.process(request.to_json())
        assert_response_error(response, 1, {
            "code": -32602,
            "message": "Invalid params",
            "data": {
                "message": (
                    "TestJsonRpcRequest.test_invalid_params.<locals>.multiply() "
                    "got an unexpected keyword argument 'c'"
                )
            }
        })

# ------------------------------------------------------------------------------

class TestJsonRpcBatchRequest:
    def test_batch(self) -> None:
        dispatcher = JsonRpcDispatcher()

        @dispatcher.method
        def add(*args: int) -> int:
            total = 0
            for i in args:
                total += i
            return total

        @dispatcher.method
        def substract(a: int, b: int) -> int:
            return a - b

        @dispatcher.method
        def hello(count: int) -> None:
            pass

        request_processor = JsonRpcRequestProcessor(dispatcher)

        request = JsonRpcBatchRequest([
            JsonRpcRequest(1, "add", [1, 2, 4]),
            JsonRpcRequest(None, "hello", [7]),
            JsonRpcRequest(5, "get", {"name": "myself"}),
            JsonRpcRequest(2, "substract", [42, 23]),
        ])
        response = request_processor.process(request.to_json())
        assert isinstance(response, JsonRpcBatchResponse)

        responses = response.responses
        assert len(responses) == 3

        assert_response_result(responses[0], 1, 7)
        assert_response_error(responses[1], 5, {"code": -32601, "message": "Method not found"})
        assert_response_result(responses[2], 2, 19)

    def test_parse_error(self) -> None:
        dispatcher = JsonRpcDispatcher()

        request_processor = JsonRpcRequestProcessor(dispatcher)
        response = request_processor.process("["
            '{"jsonrpc": "2.0", "method": "sum", "params": [1,2,4], "id": "1"},'
            '{"jsonrpc": "2.0", "method"'
        "]")
        assert_response_error(response, None, {"code": -32700, "message": "Parse error"})

    def test_no_requests(self) -> None:
        dispatcher = JsonRpcDispatcher()

        request_processor = JsonRpcRequestProcessor(dispatcher)
        response = request_processor.process("[]")
        assert_response_error(response, None, {
            "code": -32600,
            "message": "Invalid Request",
            "data": {"message": "Invalid request. Empty batch."}
        })

    def test_invalid_request(self) -> None:
        dispatcher = JsonRpcDispatcher()

        request_processor = JsonRpcRequestProcessor(dispatcher)
        response = request_processor.process("[1]")
        assert_response_error(response, None, {
            "code": -32600,
            "message": "Invalid Request",
            "data": {"message": "Invalid request. Payload must be an object or a list of objects."}
        })
