# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, BinaryIO, Callable, Type

from pylsp_jsonrpc.endpoint import Endpoint  # type: ignore[import]
from pylsp_jsonrpc.exceptions import (  # type: ignore[import]
    JsonRpcException,
    JsonRpcInvalidRequest,
    JsonRpcMethodNotFound,
)
from pylsp_jsonrpc.streams import JsonRpcStreamReader, JsonRpcStreamWriter  # type: ignore[import]

from pants.bsp.spec import (
    InitializeBuildParams,
    InitializeBuildResult,
    WorkspaceBuildTargetsParams,
    WorkspaceBuildTargetsResult,
)
from pants.engine.internals.scheduler import SchedulerSession
from pants.util.frozendict import FrozenDict

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _HandlerMapping:
    request_decoder: Callable[[dict], Any] | None
    response_type: Type
    is_notification: bool = False


BSP_HANDLER_MAPPING = {
    "build/initialize": _HandlerMapping(
        InitializeBuildParams.from_json_dict, InitializeBuildResult
    ),
    "workspace/buildTargets": _HandlerMapping(
        WorkspaceBuildTargetsParams.from_json_dict, WorkspaceBuildTargetsResult
    ),
}


def _make_error_future(exc: Exception) -> Future:
    fut: Future = Future()
    fut.set_exception(exc)
    return fut


class BSPConnection:
    _INITIALIZE_METHOD_NAME = "build/initialize"

    def __init__(
        self,
        scheduler_session: SchedulerSession,
        inbound: BinaryIO,
        outbound: BinaryIO,
        max_workers: int = 5,
    ) -> None:
        self._scheduler_session = scheduler_session
        self._inbound = JsonRpcStreamReader(inbound)
        self._outbound = JsonRpcStreamWriter(outbound)
        self._initialized = False
        self._endpoint = Endpoint(self, self._send_outbound_message, max_workers=max_workers)

    def run(self) -> None:
        """Run the listener for inbound JSON-RPC messages."""
        self._inbound.listen(self._received_inbound_message)

    def _received_inbound_message(self, msg):
        """Process each inbound JSON-RPC message."""
        _logger.info(f"_received_inbound_message: msg={msg}")
        self._endpoint.consume(msg)

    def _send_outbound_message(self, msg):
        _logger.info(f"_send_outbound_message: msg={msg}")
        self._outbound.write(msg)

    # TODO: Figure out how to run this on the `Endpoint`'s thread pool by returing a callable. For now, we
    # need to return errors as futures given that `Endpoint` only handles exceptions returned that way versus using a try ... except block.
    def _handle_inbound_message(self, *, method_name: str, params: Any):
        if not self._initialized and method_name != self._INITIALIZE_METHOD_NAME:
            return _make_error_future(
                JsonRpcException(
                    code=-32002, message=f"Client must first call `{self._INITIALIZE_METHOD_NAME}`."
                )
            )

        method_mapping = BSP_HANDLER_MAPPING.get(method_name)
        if not method_mapping:
            return _make_error_future(JsonRpcMethodNotFound.of(method_name))

        request: Any | None = None
        try:
            if method_mapping.request_decoder is not None:
                request = method_mapping.request_decoder(params)
        except Exception:
            return _make_error_future(JsonRpcInvalidRequest())

        execution_request = self._scheduler_session.execution_request(
            products=[method_mapping.response_type], subjects=[request]
        )
        returns, throws = self._scheduler_session.execute(execution_request)
        if len(returns) == 1 and len(throws) == 0:
            if method_name == self._INITIALIZE_METHOD_NAME:
                self._initialized = True
            return returns[0][1].value.to_json_dict()
        elif len(returns) == 0 and len(throws) == 1:
            raise throws[0][1].exc
        else:
            raise AssertionError(
                f"Received unexpected result from engine: returns={returns}; throws={throws}"
            )

    # Called by `Endpoint` to dispatch requests and notifications.
    # TODO: Should probably vendor `Endpoint` so we can detect notifications versus method calls, which
    # matters when ignoring unknown notifications versus erroring for unknown methods.
    def __getitem__(self, method_name):
        def handler(params):
            return self._handle_inbound_message(method_name=method_name, params=params)

        return handler


def _freeze(item: Any) -> Any:
    if item is None:
        return None
    elif isinstance(item, list) or isinstance(item, tuple):
        return tuple(_freeze(x) for x in item)
    elif isinstance(item, dict):
        result = {}
        for k, v in item.items():
            if not isinstance(k, str):
                raise AssertionError("Got non-`str` key for _freeze.")
            result[k] = _freeze(v)
        return FrozenDict(result)
    elif isinstance(item, str) or isinstance(item, int) or isinstance(item, float):
        return item
    else:
        raise AssertionError(f"Unsupported value type for _freeze: {type(item)}")
