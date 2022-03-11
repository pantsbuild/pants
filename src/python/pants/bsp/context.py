# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from pants.bsp.spec.lifecycle import InitializeBuildParams
from pants.bsp.spec.task import BSPNotification

# Wrapper type to provide BSP rules with the ability to interact with the BSP protocol driver.
#
# Note: Due to limitations in the engine's API regarding what values can be part of a query for a union rule,
# this class is stored in SessionValues. See https://github.com/pantsbuild/pants/issues/12934.
#
# Concurrency: This method can be invoked from multiple threads (for each individual request). The protocol
# driver protects against multiple threads trying to call `initialize_connection` by only allowing
# the thread processing the `build/initialize` RPC to proceed; all other requests return an error _before_
# they enter the engine (and thus would ever have a chance to access this context).
#
# Thus, while this class can mutate due to initialization, it is immutable after it has been initialized and
# is thus compatible with use in the engine.
from pants.util.dirutil import safe_mkdtemp


class BSPContext:
    """Wrapper type to provide BSP rules with the ability to interact with the BSP protocol
    driver."""

    def __init__(self) -> None:
        """Initialize the context with an empty client params.

        This is the "connection uninitialized" state.
        """
        self._lock = threading.Lock()
        self._client_params: InitializeBuildParams | None = None
        self._notify_client: Callable[[BSPNotification], None] | None = None
        self.tempdir: Path = Path(safe_mkdtemp(prefix="bsp"))

    @property
    def is_connection_initialized(self):
        with self._lock:
            return self._client_params is not None

    @property
    def client_params(self) -> InitializeBuildParams:
        with self._lock:
            if self._client_params is None:
                raise AssertionError(
                    "Attempt to access BSP context on an uninitialized connection."
                )
            return self._client_params

    def initialize_connection(
        self, client_params: InitializeBuildParams, notify_client: Callable[[BSPNotification], None]
    ) -> None:
        with self._lock:
            if self._client_params is not None:
                raise AssertionError(
                    "Attempted to set new BSP client parameters on an already-initialized connection."
                )
            self._client_params = client_params
            self._notify_client = notify_client

    def notify_client(self, notification: BSPNotification) -> None:
        if not self.is_connection_initialized:
            return
        assert self._notify_client is not None
        self._notify_client(notification)

    def __hash__(self):
        return hash(self._client_params)

    def __eq__(self, other):
        if isinstance(other, BSPContext):
            return NotImplemented
        return self._client_params == other._client_params
