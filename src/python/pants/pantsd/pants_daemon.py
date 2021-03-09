# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import sys
import time
import warnings
from typing import Any

from setproctitle import setproctitle as set_process_title

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink
from pants.bin.daemon_pants_runner import DaemonPantsRunner
from pants.engine.environment import CompleteEnvironment
from pants.engine.internals.native import Native
from pants.engine.internals.native_engine import PyExecutor
from pants.init.engine_initializer import GraphScheduler
from pants.init.logging import initialize_stdio
from pants.init.util import init_workdir
from pants.option.global_options import GlobalOptions
from pants.option.option_value_container import OptionValueContainer
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon_core import PantsDaemonCore
from pants.pantsd.process_manager import PantsDaemonProcessManager
from pants.pantsd.service.pants_service import PantsServices
from pants.pantsd.service.scheduler_service import SchedulerService
from pants.pantsd.service.store_gc_service import StoreGCService
from pants.util.contextutil import argv_as, hermetic_environment_as
from pants.util.logging import LogLevel
from pants.util.strutil import ensure_text


class PantsDaemon(PantsDaemonProcessManager):
    """A daemon that manages PantsService instances."""

    JOIN_TIMEOUT_SECONDS = 1

    class StartupFailure(Exception):
        """Represents a failure to start pantsd."""

    class RuntimeFailure(Exception):
        """Represents a pantsd failure at runtime, usually from an underlying service failure."""

    @classmethod
    def create(
        cls, options_bootstrapper: OptionsBootstrapper, env: CompleteEnvironment
    ) -> PantsDaemon:
        # Any warnings that would be triggered here are re-triggered later per-run of Pants, so we
        # silence them.
        with warnings.catch_warnings(record=True):
            bootstrap_options = options_bootstrapper.bootstrap_options
            bootstrap_options_values = bootstrap_options.for_global_scope()

        native = Native()

        executor = PyExecutor(*GlobalOptions.compute_executor_arguments(bootstrap_options_values))
        core = PantsDaemonCore(options_bootstrapper, env, executor, cls._setup_services)

        server = native.new_nailgun_server(
            executor,
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

        invalidation_globs = GlobalOptions.compute_pantsd_invalidation_globs(
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

        global_bootstrap_options = self._bootstrap_options.for_global_scope()
        # Set the process name in ps output to 'pantsd' vs './pants compile src/etc:: -ldebug'.
        set_process_title(f"pantsd [{self._build_root}]")

        # Switch log output to the daemon's log stream, and empty `env` and `argv` to encourage all
        # further usage of those variables to happen via engine APIs and options.
        self._close_stdio()
        with initialize_stdio(global_bootstrap_options), argv_as(
            tuple()
        ), hermetic_environment_as():
            # Install signal and panic handling.
            ExceptionSink.install(
                log_location=init_workdir(global_bootstrap_options), pantsd_instance=True
            )
            self._native.set_panic_handler()

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
    env = CompleteEnvironment(os.environ)
    daemon = PantsDaemon.create(options_bootstrapper, env)
    daemon.run_sync()
