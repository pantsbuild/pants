# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import logging
from concurrent.futures import Future
from typing import Any, BinaryIO, ClassVar, Protocol

from pylsp_jsonrpc.endpoint import Endpoint  # type: ignore[import]
from pylsp_jsonrpc.exceptions import (  # type: ignore[import]
    JsonRpcException,
    JsonRpcInvalidRequest,
    JsonRpcMethodNotFound,
)
from pylsp_jsonrpc.streams import JsonRpcStreamReader, JsonRpcStreamWriter  # type: ignore[import]

from pants.bsp.context import BSPContext
from pants.bsp.spec.notification import BSPNotification
from pants.core.util_rules.environments import determine_bootstrap_environment
from pants.engine.environment import EnvironmentName
from pants.engine.fs import Workspace
from pants.engine.internals.scheduler import SchedulerSession
from pants.engine.internals.selectors import Params
from pants.engine.unions import UnionMembership, union

_logger = logging.getLogger(__name__)


class BSPRequestTypeProtocol(Protocol):
    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> Any: ...


class BSPResponseTypeProtocol(Protocol):
    def to_json_dict(self) -> dict[str, Any]: ...


@union(in_scope_types=[EnvironmentName])
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


def _make_error_future(exc: Exception) -> Future:
    fut: Future = Future()
    fut.set_exception(exc)
    return fut


class BSPConnection:
    _INITIALIZE_METHOD_NAME = "build/initialize"
    _SHUTDOWN_METHOD_NAME = "build/shutdown"
    _EXIT_NOTIFICATION_NAME = "build/exit"

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
        # TODO: We might eventually want to make this configurable.
        self._env_name = determine_bootstrap_environment(self._scheduler_session)
        self._inbound = JsonRpcStreamReader(inbound)
        self._outbound = JsonRpcStreamWriter(outbound)
        self._context: BSPContext = context
        self._endpoint = Endpoint(self, self._send_outbound_message, max_workers=max_workers)

        self._handler_mappings: dict[str, type[BSPHandlerMapping]] = {}
        impls = union_membership.get(BSPHandlerMapping)
        for impl in impls:
            self._handler_mappings[impl.method_name] = impl

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

    # TODO: Figure out how to run this on the `Endpoint`'s thread pool by returning a callable. For now, we
    # need to return errors as futures given that `Endpoint` only handles exceptions returned that way versus using a try ... except block.
    def _handle_inbound_message(self, *, method_name: str, params: Any):
        # If the connection is not yet initialized and this is not the initialization request, BSP requires
        # returning an error for methods (and to discard all notifications).
        #
        # Concurrency: This method can be invoked from multiple threads (for each individual request). By returning
        # an error for all other requests, only the thread running the initialization RPC should be able to proceed.
        # This ensures that we can safely call `initialize_connection` on the BSPContext with the client-supplied
        # init parameters without worrying about multiple threads. (Not entirely true though as this does not handle
        # the client making multiple concurrent initialization RPCs, but which would violate the protocol in any case.)
        if (
            not self._context.is_connection_initialized
            and method_name != self._INITIALIZE_METHOD_NAME
        ):
            return _make_error_future(
                JsonRpcException(
                    code=-32002, message=f"Client must first call `{self._INITIALIZE_METHOD_NAME}`."
                )
            )

        # Handle the `build/shutdown` method and `build/exit` notification.
        if method_name == self._SHUTDOWN_METHOD_NAME:
            # Return no-op success for the `build/shutdown` method. This doesn't actually cause the server to
            # exit. That will occur once the client sends the `build/exit` notification.
            return None
        elif method_name == self._EXIT_NOTIFICATION_NAME:
            # The `build/exit` notification directs the BSP server to immediately exit.
            # The read-dispatch loop will exit once it notices that the inbound handle is closed. So close the
            # inbound handle (and outbound handle for completeness) and then return to the dispatch loop
            # to trigger the exit.
            self._inbound.close()
            self._outbound.close()
            return None

        method_mapping = self._handler_mappings.get(method_name)
        if not method_mapping:
            return _make_error_future(JsonRpcMethodNotFound.of(method_name))

        try:
            request = method_mapping.request_type.from_json_dict(params)
        except Exception:
            return _make_error_future(JsonRpcInvalidRequest())

        # TODO: This should not be necessary: see https://github.com/pantsbuild/pants/issues/15435.
        self._scheduler_session.new_run_id()

        workspace = Workspace(self._scheduler_session)
        params = Params(request, workspace, self._env_name)
        execution_request = self._scheduler_session.execution_request(
            requests=[(method_mapping.response_type, params)],
        )
        (result,) = self._scheduler_session.execute(execution_request)
        # Initialize the BSPContext with the client-supplied init parameters. See earlier comment on why this
        # call to `BSPContext.initialize_connection` is safe.
        if method_name == self._INITIALIZE_METHOD_NAME:
            self._context.initialize_connection(request, self.notify_client)
        return result.to_json_dict()

    # Called by `Endpoint` to dispatch requests and notifications.
    # TODO: Should probably vendor `Endpoint` so we can detect notifications versus method calls, which
    # matters when ignoring unknown notifications versus erroring for unknown methods.
    def __getitem__(self, method_name):
        def handler(params):
            return self._handle_inbound_message(method_name=method_name, params=params)

        return handler

    def notify_client(self, notification: BSPNotification) -> None:
        try:
            self._endpoint.notify(notification.notification_name, notification.to_json_dict())
        except Exception as ex:
            _logger.warning(f"Received exception while notifying BSP client: {ex}")
