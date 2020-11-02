# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import sys
import time
import warnings
from contextlib import contextmanager
from typing import Any, Iterator

from setproctitle import setproctitle as set_process_title

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink, SignalHandler
from pants.bin.daemon_pants_runner import DaemonPantsRunner
from pants.engine.internals.native import Native
from pants.init.engine_initializer import GraphScheduler
from pants.init.logging import setup_logging, setup_logging_to_file, setup_warning_filtering
from pants.init.options_initializer import OptionsInitializer
from pants.option.option_value_container import OptionValueContainer
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon_core import PantsDaemonCore
from pants.pantsd.process_manager import PantsDaemonProcessManager
from pants.pantsd.service.pants_service import PantsServices
from pants.pantsd.service.scheduler_service import SchedulerService
from pants.pantsd.service.store_gc_service import StoreGCService
from pants.util.contextutil import stdio_as
from pants.util.logging import LogLevel
from pants.util.strutil import ensure_text


class PantsDaemon(PantsDaemonProcessManager):
    """A daemon that manages PantsService instances."""

    JOIN_TIMEOUT_SECONDS = 1
    LOG_NAME = "pantsd.log"

    class StartupFailure(Exception):
        """Represents a failure to start pantsd."""

    class RuntimeFailure(Exception):
        """Represents a pantsd failure at runtime, usually from an underlying service failure."""

    @classmethod
    def create(cls, options_bootstrapper: OptionsBootstrapper) -> "PantsDaemon":

        with warnings.catch_warnings(record=True):
            bootstrap_options = options_bootstrapper.bootstrap_options
            bootstrap_options_values = bootstrap_options.for_global_scope()

        setup_warning_filtering(bootstrap_options_values.ignore_pants_warnings or [])

        native = Native()
        native.override_thread_logging_destination_to_just_pantsd()

        core = PantsDaemonCore(cls._setup_services)

        server = native.new_nailgun_server(
            bootstrap_options_values.pantsd_pailgun_port,
            DaemonPantsRunner(core),
        )

        return PantsDaemon(
            native=native,
            work_dir=bootstrap_options_values.pants_workdir,
            log_level=bootstrap_options_values.level,
            server=server,
            core=core,
            metadata_base_dir=bootstrap_options_values.pants_subprocessdir,
            bootstrap_options=bootstrap_options,
        )

    @staticmethod
    def _setup_services(
        bootstrap_options: OptionValueContainer,
        graph_scheduler: GraphScheduler,
    ):
        """Initialize pantsd services.

        :returns: A PantsServices instance.
        """
        build_root = get_buildroot()

        invalidation_globs = OptionsInitializer.compute_pantsd_invalidation_globs(
            build_root,
            bootstrap_options,
        )

        scheduler_service = SchedulerService(
            graph_scheduler=graph_scheduler,
            build_root=build_root,
            invalidation_globs=invalidation_globs,
            pidfile=PantsDaemon.metadata_file_path(
                "pantsd", "pid", bootstrap_options.pants_subprocessdir
            ),
            pid=os.getpid(),
            max_memory_usage_in_bytes=bootstrap_options.pantsd_max_memory_usage,
        )

        store_gc_service = StoreGCService(graph_scheduler.scheduler)
        return PantsServices(services=(scheduler_service, store_gc_service))

    def __init__(
        self,
        native: Native,
        work_dir: str,
        log_level: LogLevel,
        server: Any,
        core: PantsDaemonCore,
        metadata_base_dir: str,
        bootstrap_options: Options,
    ):
        """
        NB: A PantsDaemon instance is generally instantiated via `create`.

        :param native: A `Native` instance.
        :param work_dir: The pants work directory.
        :param log_level: The log level to use for daemon logging.
        :param server: A native PyNailgunServer instance (not currently a nameable type).
        :param core: A PantsDaemonCore.
        :param metadata_base_dir: The ProcessManager metadata base dir.
        :param bootstrap_options: The bootstrap options.
        """
        super().__init__(bootstrap_options, daemon_entrypoint=__name__)
        self._native = native
        self._build_root = get_buildroot()
        self._work_dir = work_dir
        self._server = server
        self._core = core
        self._bootstrap_options = bootstrap_options

        self._logger = logging.getLogger(__name__)

    @staticmethod
    def _close_stdio():
        """Close stdio streams to avoid output in the tty that launched pantsd."""
        for fd in (sys.stdin, sys.stdout, sys.stderr):
            file_no = fd.fileno()
            fd.flush()
            fd.close()
            os.close(file_no)

    @contextmanager
    def _pantsd_logging(self) -> Iterator[None]:
        """A context manager that runs with pantsd logging.

        Asserts that stdio (represented by file handles 0, 1, 2) is closed to ensure that we can
        safely reuse those fd numbers.
        """

        # Ensure that stdio is closed so that we can safely reuse those file descriptors.
        for fd in (0, 1, 2):
            try:
                os.fdopen(fd)
                raise AssertionError(f"pantsd logging cannot initialize while stdio is open: {fd}")
            except OSError:
                pass

        # Redirect stdio to /dev/null for the rest of the run to reserve those file descriptors.
        with stdio_as(stdin_fd=-1, stdout_fd=-1, stderr_fd=-1):
            # Reinitialize logging for the daemon context.
            global_options = self._bootstrap_options.for_global_scope()
            setup_logging(global_options, stderr_logging=False)

            log_dir = os.path.join(self._work_dir, self.name)
            setup_logging_to_file(global_options.level, log_dir=log_dir, log_filename=self.LOG_NAME)

            self._logger.debug("Logging reinitialized in pantsd context")
            yield

    def _initialize_metadata(self) -> None:
        """Writes out our pid and other metadata.

        Order matters a bit here, because technically all that is necessary to connect is the port,
        and Services are lazily initialized by the core when a connection is established. Our pid
        needs to be on disk before that happens.
        """

        # Write the pidfile. The SchedulerService will monitor it after a grace period.
        self.write_pid()
        self.write_process_name()
        self.write_fingerprint(ensure_text(self.options_fingerprint))
        self._logger.debug(f"pantsd running with PID: {self.pid}")
        self.write_socket(self._server.port())

    def run_sync(self):
        """Synchronously run pantsd."""
        os.environ.pop("PYTHONPATH")

        # Switch log output to the daemon's log stream from here forward.
        self._close_stdio()
        with self._pantsd_logging():

            ExceptionSink.reset_signal_handler(SignalHandler(pantsd_instance=True))

            # Reset the log location and the backtrace preference from the global bootstrap options.
            global_bootstrap_options = self._bootstrap_options.for_global_scope()
            ExceptionSink.reset_log_location(global_bootstrap_options.pants_workdir)

            self._native.set_panic_handler()

            # Set the process name in ps output to 'pantsd' vs './pants compile src/etc:: -ldebug'.
            set_process_title(f"pantsd [{self._build_root}]")

            self._initialize_metadata()

            # Check periodically whether the core is valid, and exit if it is not.
            while self._core.is_valid():
                time.sleep(self.JOIN_TIMEOUT_SECONDS)

            # We're exiting: join the server to avoid interrupting ongoing runs.
            self._logger.info("Waiting for ongoing runs to complete before exiting...")
            self._native.nailgun_server_await_shutdown(self._server)
            self._logger.info("Exiting pantsd")


def launch_new_pantsd_instance():
    """An external entrypoint that spawns a new pantsd instance."""

    options_bootstrapper = OptionsBootstrapper.create(
        env=os.environ, args=sys.argv, allow_pantsrc=True
    )
    daemon = PantsDaemon.create(options_bootstrapper)
    daemon.run_sync()
