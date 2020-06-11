# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import threading
from typing import Optional

from typing_extensions import Protocol

from pants.init.engine_initializer import EngineInitializer, LegacyGraphScheduler
from pants.init.options_initializer import BuildConfigInitializer
from pants.option.option_value_container import OptionValueContainer
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.option.options_fingerprinter import OptionsFingerprinter
from pants.option.scope import GLOBAL_SCOPE
from pants.pantsd.service.pants_service import PantsServices

logger = logging.getLogger(__name__)


class PantsServicesConstructor(Protocol):
    def __call__(
        self, bootstrap_options: OptionValueContainer, legacy_graph_scheduler: LegacyGraphScheduler,
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

        self._scheduler: Optional[LegacyGraphScheduler] = None
        self._services: Optional[PantsServices] = None
        self._fingerprint: Optional[str] = None

    def is_valid(self) -> bool:
        """Return true if the core is valid.

        This mostly means confirming that if any services have been started, that they are still
        alive.
        """
        with self._lifecycle_lock:
            if self._services is None:
                return True
            return self._services.are_all_alive()

    def prepare_scheduler(self, options_bootstrapper: OptionsBootstrapper) -> LegacyGraphScheduler:
        """Get a scheduler for the given options_bootstrapper.

        Runs in a client context (generally in DaemonPantsRunner) so logging is sent to the client.
        """
        bootstrap_options = options_bootstrapper.bootstrap_options
        bootstrap_options_values = bootstrap_options.for_global_scope()

        # Compute the fingerprint of the given options. This only takes account of options marked
        # `daemon=True`, which are the options consumed by the Scheduler.
        #
        # TODO: Rename the `daemon` kwarg to `scheduler`, or similar.
        options_fingerprint = OptionsFingerprinter.combined_options_fingerprint_for_scope(
            GLOBAL_SCOPE, bootstrap_options, fingerprint_key="daemon", invert=True
        )

        with self._lifecycle_lock:
            if self._scheduler is None or options_fingerprint != self._fingerprint:
                if self._scheduler:
                    logger.info("initialization options changed: reinitializing pantsd...")
                else:
                    logger.info("initializing pantsd...")
                # The fingerprint mismatches, either because this is the first run (and there is no
                # fingerprint) or because relevant options have changed. Create a new scheduler and services.
                if self._services:
                    self._services.shutdown()
                build_config = BuildConfigInitializer.get(options_bootstrapper)
                self._scheduler = EngineInitializer.setup_legacy_graph(
                    options_bootstrapper, build_config
                )
                self._services = self._services_constructor(
                    bootstrap_options_values, self._scheduler
                )
                self._fingerprint = options_fingerprint
                logger.info("pantsd initialized.")
            return self._scheduler
