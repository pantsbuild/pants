# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import os
import sys
import time
import warnings
from pathlib import PurePath
from typing import Any

from setproctitle import setproctitle as set_process_title

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink
from pants.bin.daemon_pants_runner import DaemonPantsRunner
from pants.engine.internals import native_engine
from pants.init.engine_initializer import GraphScheduler
from pants.init.logging import initialize_stdio, pants_log_path
from pants.init.util import init_workdir
from pants.option.global_options import GlobalOptions, LocalStoreOptions
from pants.option.option_value_container import OptionValueContainer
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon_core import PantsDaemonCore
from pants.pantsd.process_manager import PantsDaemonProcessManager
from pants.pantsd.service.pants_service import PantsServices
from pants.pantsd.service.scheduler_service import SchedulerService
from pants.pantsd.service.store_gc_service import StoreGCService
from pants.util.contextutil import argv_as, hermetic_environment_as
from pants.util.dirutil import safe_open
from pants.util.strutil import ensure_text


class PantsDaemon(PantsDaemonProcessManager):
    """A daemon that manages PantsService instances."""

    JOIN_TIMEOUT_SECONDS = 1

    class StartupFailure(Exception):
        """Represents a failure to start pantsd."""

    class RuntimeFailure(Exception):
        """Represents a pantsd failure at runtime, usually from an underlying service failure."""

    @classmethod
    def create(cls, options_bootstrapper: OptionsBootstrapper) -> PantsDaemon:
        # Any warnings that would be triggered here are re-triggered later per-run of Pants, so we
        # silence them.
        with warnings.catch_warnings(record=True):
            bootstrap_options = options_bootstrapper.bootstrap_options
            bootstrap_options_values = bootstrap_options.for_global_scope()

        executor = GlobalOptions.create_py_executor(bootstrap_options_values)
        core = PantsDaemonCore(options_bootstrapper, executor, cls._setup_services)

        server = native_engine.nailgun_server_create(
            executor,
            bootstrap_options_values.pantsd_pailgun_port,
            DaemonPantsRunner(core),
        )

        return PantsDaemon(
            work_dir=bootstrap_options_values.pants_workdir,
            server=server,
            core=core,
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

        store_gc_service = StoreGCService(
            graph_scheduler.scheduler,
            local_store_options=LocalStoreOptions.from_options(bootstrap_options),
        )
        return PantsServices(services=(scheduler_service, store_gc_service))

    def __init__(
        self,
        work_dir: str,
        server: Any,
        core: PantsDaemonCore,
        bootstrap_options: Options,
    ):
        """
        NB: A PantsDaemon instance is generally instantiated via `create`.

        :param work_dir: The pants work directory.
        :param server: A native PyNailgunServer instance (not currently a nameable type).
        :param core: A PantsDaemonCore.
        :param bootstrap_options: The bootstrap options.
        """
        super().__init__(bootstrap_options, daemon_entrypoint=__name__)
        self._build_root = get_buildroot()
        self._work_dir = work_dir
        self._server = server
        self._core = core
        self._bootstrap_options = bootstrap_options

        self._logger = logging.getLogger(__name__)

    def _close_stdio(self, log_path: PurePath):
        """Close stdio and append to a log path instead.

        The vast majority of Python-level IO will be re-routed to thread-local destinations by
        `initialize_stdio`, but we close stdio to avoid any stray output in the tty that launched
        pantsd.

        Rather than leaving 0, 1, 2 dangling though, we open replacements as a backstop for fatal
        errors or unmodified code (such as Rust panic handlers) that might expect them to be valid
        file handles.
        """
        for attr, writable in (("stdin", False), ("stdout", True), ("stderr", True)):
            # Close the old.
            fd = getattr(sys, attr)
            fileno = fd.fileno()
            fd.flush()
            fd.close()

            # Open the new.
            temp_fd = safe_open(log_path, "w") if writable else open(os.devnull)
            os.dup2(temp_fd.fileno(), fileno)
            setattr(sys, attr, os.fdopen(fileno, mode=("w" if writable else "r")))
        sys.__stdin__, sys.__stdout__, sys.__stderr__ = sys.stdin, sys.stdout, sys.stderr  # type: ignore[assignment]

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
        self._close_stdio(pants_log_path(PurePath(global_bootstrap_options.pants_workdir)))
        with initialize_stdio(global_bootstrap_options), argv_as(
            tuple()
        ), hermetic_environment_as():
            # Install signal and panic handling.
            ExceptionSink.install(
                log_location=init_workdir(global_bootstrap_options), pantsd_instance=True
            )
            native_engine.maybe_set_panic_handler()

            self._initialize_metadata()

            # Check periodically whether the core is valid, and exit if it is not.
            while self._core.is_valid():
                time.sleep(self.JOIN_TIMEOUT_SECONDS)

            # We're exiting: purge our metadata to prevent new connections, then join the server
            # to avoid interrupting ongoing runs.
            self.purge_metadata(force=True)
            self._logger.info("Waiting for ongoing runs to complete before exiting...")
            native_engine.nailgun_server_await_shutdown(self._server)
            # Then shutdown the PantsDaemonCore, which will shut down any live Scheduler.
            self._logger.info("Waiting for Sessions to complete before exiting...")
            self._core.shutdown()
            self._logger.info("Exiting pantsd")


def launch_new_pantsd_instance():
    """An external entrypoint that spawns a new pantsd instance."""

    options_bootstrapper = OptionsBootstrapper.create(
        env=os.environ, args=sys.argv, allow_pantsrc=True
    )
    daemon = PantsDaemon.create(options_bootstrapper)
    daemon.run_sync()
