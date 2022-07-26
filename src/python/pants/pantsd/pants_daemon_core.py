# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import threading
from contextlib import contextmanager
from typing import Iterator

from typing_extensions import Protocol

from pants.build_graph.build_configuration import BuildConfiguration
from pants.engine.environment import CompleteEnvironment
from pants.engine.internals.native_engine import PyExecutor
from pants.init.engine_initializer import EngineInitializer, GraphScheduler
from pants.init.options_initializer import OptionsInitializer
from pants.option.global_options import AuthPluginResult, DynamicRemoteOptions
from pants.option.option_value_container import OptionValueContainer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.options_fingerprinter import OptionsFingerprinter
from pants.option.scope import GLOBAL_SCOPE
from pants.pantsd.service.pants_service import PantsServices

logger = logging.getLogger(__name__)


class PantsServicesConstructor(Protocol):
    def __call__(
        self,
        bootstrap_options: OptionValueContainer,
        graph_scheduler: GraphScheduler,
    ) -> PantsServices:
        ...


class PantsDaemonCore:
    """A container for the state of a PantsDaemon that is affected by the bootstrap options.

    This class also serves to avoid a reference cycle between DaemonPantsRunner and PantsDaemon,
    which both have a reference to the core, and use it to get access to the Scheduler and current
    PantsServices.
    """

    def __init__(
        self,
        options_bootstrapper: OptionsBootstrapper,
        executor: PyExecutor,
        services_constructor: PantsServicesConstructor,
    ):
        self._options_initializer = OptionsInitializer(options_bootstrapper, executor)
        self._executor = executor
        self._services_constructor = services_constructor
        self._lifecycle_lock = threading.RLock()
        # N.B. This Event is used as nothing more than an atomic flag - nothing waits on it.
        self._kill_switch = threading.Event()

        self._scheduler: GraphScheduler | None = None
        self._services: PantsServices | None = None
        self._fingerprint: str | None = None

        self._prior_dynamic_remote_options: DynamicRemoteOptions | None = None
        self._prior_auth_plugin_result: AuthPluginResult | None = None

    def is_valid(self) -> bool:
        """Return true if the core is valid.

        This mostly means confirming that if any services have been started, that they are still
        alive.
        """
        if self._kill_switch.is_set():
            logger.error("Client failed to create a Scheduler: shutting down.")
            return False
        with self._lifecycle_lock:
            if self._services is None:
                return True
            return self._services.are_all_alive()

    @contextmanager
    def _handle_exceptions(self) -> Iterator[None]:
        try:
            yield
        except Exception as e:
            self._kill_switch.set()
            self._scheduler = None
            raise e

    def _initialize(
        self,
        options_fingerprint: str,
        bootstrap_options: OptionValueContainer,
        build_config: BuildConfiguration,
        dynamic_remote_options: DynamicRemoteOptions,
        scheduler_restart_explanation: str | None,
    ) -> None:
        """(Re-)Initialize the scheduler.

        Must be called under the lifecycle lock.
        """
        try:
            logger.info(
                f"{scheduler_restart_explanation}: reinitializing scheduler..."
                if scheduler_restart_explanation
                else "Initializing scheduler..."
            )
            if self._services:
                self._services.shutdown()
            self._scheduler = EngineInitializer.setup_graph(
                bootstrap_options, build_config, dynamic_remote_options, self._executor
            )

            self._services = self._services_constructor(bootstrap_options, self._scheduler)
            self._fingerprint = options_fingerprint
            logger.info("Scheduler initialized.")
        except Exception as e:
            self._kill_switch.set()
            self._scheduler = None
            raise e

    def prepare(
        self, options_bootstrapper: OptionsBootstrapper, env: CompleteEnvironment
    ) -> tuple[GraphScheduler, OptionsInitializer]:
        """Get a scheduler for the given options_bootstrapper.

        Runs in a client context (generally in DaemonPantsRunner) so logging is sent to the client.
        """

        with self._handle_exceptions():
            build_config, options = self._options_initializer.build_config_and_options(
                options_bootstrapper, env, raise_=True
            )

        scheduler_restart_explanation: str | None = None

        # Because these options are computed dynamically via side-effects like reading from a file,
        # they need to be re-evaluated every run. We only reinitialize the scheduler if changes
        # were made, though.
        dynamic_remote_options, auth_plugin_result = DynamicRemoteOptions.from_options(
            options,
            env,
            self._prior_auth_plugin_result,
            remote_auth_plugin_func=build_config.remote_auth_plugin_func,
        )
        remote_options_changed = (
            self._prior_dynamic_remote_options is not None
            and dynamic_remote_options != self._prior_dynamic_remote_options
        )
        if remote_options_changed:
            scheduler_restart_explanation = "Remote cache/execution options updated"

        # Compute the fingerprint of the bootstrap options. Note that unlike
        # PantsDaemonProcessManager (which fingerprints only `daemon=True` options), this
        # fingerprints all fingerprintable options in the bootstrap options, which are
        # all used to construct a Scheduler.
        options_fingerprint = OptionsFingerprinter.combined_options_fingerprint_for_scope(
            GLOBAL_SCOPE,
            options_bootstrapper.bootstrap_options,
        )
        bootstrap_options_changed = (
            self._fingerprint is not None and options_fingerprint != self._fingerprint
        )
        if bootstrap_options_changed:
            scheduler_restart_explanation = "Initialization options changed"

        with self._lifecycle_lock:
            if self._scheduler is None or scheduler_restart_explanation:
                # The fingerprint mismatches, either because this is the first run (and there is no
                # fingerprint) or because relevant options have changed. Create a new scheduler
                # and services.
                bootstrap_options = options.bootstrap_option_values()
                assert bootstrap_options is not None
                with self._handle_exceptions():
                    self._initialize(
                        options_fingerprint,
                        bootstrap_options,
                        build_config,
                        dynamic_remote_options,
                        scheduler_restart_explanation,
                    )

            self._prior_dynamic_remote_options = dynamic_remote_options
            self._prior_auth_plugin_result = auth_plugin_result

            assert self._scheduler is not None
            return self._scheduler, self._options_initializer

    def shutdown(self) -> None:
        with self._lifecycle_lock:
            if self._services is not None:
                self._services.shutdown()
                self._services = None
            if self._scheduler is not None:
                self._scheduler.scheduler.shutdown()
                self._scheduler = None
