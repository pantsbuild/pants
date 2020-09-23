# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import threading
from typing import Optional

from typing_extensions import Protocol

from pants.init.engine_initializer import EngineInitializer, GraphScheduler
from pants.init.logging import setup_warning_filtering
from pants.init.options_initializer import BuildConfigInitializer
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

    def __init__(self, services_constructor: PantsServicesConstructor):
        self._services_constructor = services_constructor
        self._lifecycle_lock = threading.RLock()
        # N.B. This Event is used as nothing more than an atomic flag - nothing waits on it.
        self._kill_switch = threading.Event()

        self._scheduler: Optional[GraphScheduler] = None
        self._services: Optional[PantsServices] = None
        self._fingerprint: Optional[str] = None

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

    def _init_scheduler(
        self, options_fingerprint: str, options_bootstrapper: OptionsBootstrapper
    ) -> None:
        """(Re-)Initialize the scheduler.

        Must be called under the lifecycle lock.
        """
        try:
            if self._scheduler:
                logger.info("initialization options changed: reinitializing pantsd...")
            else:
                logger.info("initializing pantsd...")
            if self._services:
                self._services.shutdown()
            build_config = BuildConfigInitializer.get(options_bootstrapper)
            self._scheduler = EngineInitializer.setup_graph(options_bootstrapper, build_config)
            bootstrap_options_values = options_bootstrapper.bootstrap_options.for_global_scope()
            setup_warning_filtering(bootstrap_options_values.ignore_pants_warnings or [])

            self._services = self._services_constructor(bootstrap_options_values, self._scheduler)
            self._fingerprint = options_fingerprint
            logger.info("pantsd initialized.")
        except Exception as e:
            self._kill_switch.set()
            self._scheduler = None
            raise e

    def prepare_scheduler(self, options_bootstrapper: OptionsBootstrapper) -> GraphScheduler:
        """Get a scheduler for the given options_bootstrapper.

        Runs in a client context (generally in DaemonPantsRunner) so logging is sent to the client.
        """

        # Compute the fingerprint of the bootstrap options. Note that unlike
        # PantsDaemonProcessManager (which fingerprints only `daemon=True` options), this
        # fingerprints all fingerprintable options in the bootstrap options, which are
        # all used to construct a Scheduler.
        options_fingerprint = OptionsFingerprinter.combined_options_fingerprint_for_scope(
            GLOBAL_SCOPE,
            options_bootstrapper.bootstrap_options,
            invert=True,
        )

        with self._lifecycle_lock:
            if self._scheduler is None or options_fingerprint != self._fingerprint:
                # The fingerprint mismatches, either because this is the first run (and there is no
                # fingerprint) or because relevant options have changed. Create a new scheduler and services.
                self._init_scheduler(options_fingerprint, options_bootstrapper)
                assert self._scheduler is not None
            return self._scheduler
