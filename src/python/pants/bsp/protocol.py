# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from concurrent.futures import Future
from dataclasses import dataclass
from threading import RLock
from typing import Any, BinaryIO, ClassVar

from pylsp_jsonrpc.endpoint import Endpoint  # type: ignore[import]
from pylsp_jsonrpc.exceptions import (  # type: ignore[import]
    JsonRpcException,
    JsonRpcInvalidRequest,
    JsonRpcMethodNotFound,
)
from pylsp_jsonrpc.streams import JsonRpcStreamReader, JsonRpcStreamWriter  # type: ignore[import]

from pants.bsp.spec import InitializeBuildParams
from pants.engine.internals.scheduler import SchedulerSession
from pants.engine.unions import UnionMembership, union

try:
    from typing import Protocol  # Python 3.8+
except ImportError:
    # See https://github.com/python/mypy/issues/4427 re the ignore
    from typing_extensions import Protocol  # type: ignore

_logger = logging.getLogger(__name__)


class BSPRequestTypeProtocol(Protocol):
    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> Any:
        ...


class BSPResponseTypeProtocol(Protocol):
    def to_json_dict(self) -> dict[str, Any]:
        ...


@union
class BSPHandlerMapping:
    """Union type for rules to register handlers for BSP methods."""

    # Name of the JSON-RPC method to be handled.
    method_name: ClassVar[str]

    # Type requested from the engine. This will be provided as the "subject" of an engine query.
    # Must implement class method `from_json_dict`.
    request_type: type[BSPRequestTypeProtocol]

    # Type produced by the handler rule. This will be requested as the "product" of the engine query.
    # Must implement instance method `to_json_dict`.
    response_type: type[BSPResponseTypeProtocol]

    # True if this handler is for a notification.
    # TODO: Consider how to pass notifications (which do not have responses) to the engine rules.
    is_notification: bool = False


# Note: Due to limitations in the engine's API regarding what values can be part of a query for a union rule,
# this class is stored in SessionValues. See https://github.com/pantsbuild/pants/issues/12934.
# We still need to update the `client_params` value after the connection is initialized, so `update_client_params`
# accomplishes that outside of the engine. Thus, while this class is mutable, it is **not** mutated during calls
# into the engine. Thus, it is configured to implement `hash`.
@dataclass(unsafe_hash=True)
class BSPContext:
    """Wrapper type to provide rules with the ability to interact with the BSP protocol driver."""

    client_params: InitializeBuildParams | None

    def update_client_params(self, new_client_params: InitializeBuildParams) -> None:
        if self.client_params is not None:
            raise AssertionError(
                "Attempted to set new `client_params` on BSPContext over existing `client_params`."
            )
        self.client_params = new_client_params


def _make_error_future(exc: Exception) -> Future:
    fut: Future = Future()
    fut.set_exception(exc)
    return fut


class BSPConnection:
    _INITIALIZE_METHOD_NAME = "build/initialize"

    def __init__(
        self,
        scheduler_session: SchedulerSession,
        union_membership: UnionMembership,
        context: BSPContext,
        inbound: BinaryIO,
        outbound: BinaryIO,
        max_workers: int = 5,
    ) -> None:
        self._scheduler_session = scheduler_session
        self._inbound = JsonRpcStreamReader(inbound)
        self._outbound = JsonRpcStreamWriter(outbound)
        self._initialized_lock = RLock()
        self._initialized_value = False
        self._context: BSPContext = context
        self._endpoint = Endpoint(self, self._send_outbound_message, max_workers=max_workers)

        self._handler_mappings: dict[str, type[BSPHandlerMapping]] = {}
        impls = union_membership.get(BSPHandlerMapping)
        for impl in impls:
            self._handler_mappings[impl.method_name] = impl

    @property
    def _initialized(self) -> bool:
        with self._initialized_lock:
            return self._initialized_value

    @_initialized.setter
    def _initialized(self, new_value: bool) -> None:
        with self._initialized_lock:
            self._initialized_value = new_value

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

        method_mapping = self._handler_mappings.get(method_name)
        if not method_mapping:
            return _make_error_future(JsonRpcMethodNotFound.of(method_name))

        try:
            request = method_mapping.request_type.from_json_dict(params)
        except Exception:
            return _make_error_future(JsonRpcInvalidRequest())

        execution_request = self._scheduler_session.execution_request(
            products=[method_mapping.response_type],
            subjects=[request],
        )
        returns, throws = self._scheduler_session.execute(execution_request)
        if len(returns) == 1 and len(throws) == 0:
            if method_name == self._INITIALIZE_METHOD_NAME:
                self._context.update_client_params(request)
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
