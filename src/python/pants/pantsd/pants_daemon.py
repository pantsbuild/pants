# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
import sys
import time
from contextlib import contextmanager
from typing import IO, Any, Iterator

from setproctitle import setproctitle as set_process_title

from pants.base.build_environment import get_buildroot
from pants.base.exception_sink import ExceptionSink
from pants.bin.daemon_pants_runner import DaemonPantsRunner
from pants.engine.internals.native import Native
from pants.init.engine_initializer import LegacyGraphScheduler
from pants.init.logging import clear_logging_handlers, init_rust_logger, setup_logging_to_file
from pants.init.options_initializer import OptionsInitializer
from pants.option.option_value_container import OptionValueContainer
from pants.option.options import Options
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.pants_daemon_core import PantsDaemonCore
from pants.pantsd.process_manager import PantsDaemonProcessManager
from pants.pantsd.service.fs_event_service import FSEventService
from pants.pantsd.service.pants_service import PantsServices
from pants.pantsd.service.scheduler_service import SchedulerService
from pants.pantsd.service.store_gc_service import StoreGCService
from pants.pantsd.watchman_launcher import WatchmanLauncher
from pants.util.contextutil import stdio_as
from pants.util.logging import LogLevel
from pants.util.strutil import ensure_text


class _LoggerStream(object):
    """A sys.std{out,err} replacement that pipes output to a logger.

    N.B. `logging.Logger` expects unicode. However, most of our outstream logic, such as in
    `exiter.py`, will use `sys.std{out,err}.buffer` and thus a bytes interface. So, we must provide
    a `buffer` property, and change the semantics of the buffer to always convert the message to
    unicode. This is an unfortunate code smell, as `logging` does not expose a bytes interface so
    this is the best solution we could think of.
    """

    def __init__(self, logger, log_level, handler):
        """
        :param logging.Logger logger: The logger instance to emit writes to.
        :param int log_level: The log level to use for the given logger.
        :param Handler handler: The underlying log handler, for determining the fileno
                                to support faulthandler logging.
        """
        self._logger = logger
        self._log_level = log_level
        self._handler = handler

    def write(self, msg):
        msg = ensure_text(msg)
        for line in msg.rstrip().splitlines():
            # The log only accepts text, and will raise a decoding error if the default encoding is ascii
            # if provided a bytes input for unicode text.
            line = ensure_text(line)
            self._logger.log(self._log_level, line.rstrip())

    def flush(self):
        return

    def isatty(self):
        return False

    def fileno(self):
        return self._handler.stream.fileno()

    @property
    def buffer(self):
        return self


class PantsDaemon(PantsDaemonProcessManager):
    """A daemon that manages PantsService instances."""

    JOIN_TIMEOUT_SECONDS = 1
    LOG_NAME = "pantsd.log"

    class StartupFailure(Exception):
        """Represents a failure to start pantsd."""

    class RuntimeFailure(Exception):
        """Represents a pantsd failure at runtime, usually from an underlying service failure."""

    @classmethod
    def create(cls, options_bootstrapper) -> "PantsDaemon":
        """
        :param OptionsBootstrapper options_bootstrapper: The bootstrap options.
        :param bool full_init: Whether or not to fully initialize an engine et al for the purposes
                                of spawning a new daemon. `full_init=False` is intended primarily
                                for lightweight lifecycle checks (since there is a ~1s overhead to
                                initialize the engine). See the impl of `maybe_launch` for an example
                                of the intended usage.
        """
        native = Native()
        native.override_thread_logging_destination_to_just_pantsd()

        bootstrap_options = options_bootstrapper.bootstrap_options
        bootstrap_options_values = bootstrap_options.for_global_scope()

        core = PantsDaemonCore(cls._setup_services)

        server = native.new_nailgun_server(
            bootstrap_options_values.pantsd_pailgun_port, DaemonPantsRunner(core),
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
        bootstrap_options: OptionValueContainer, legacy_graph_scheduler: LegacyGraphScheduler,
    ):
        """Initialize pantsd services.

        :returns: A PantsServices instance.
        """
        build_root = get_buildroot()

        # TODO: https://github.com/pantsbuild/pants/issues/3479
        watchman_launcher = WatchmanLauncher.create(bootstrap_options)
        watchman_launcher.maybe_launch()
        watchman = watchman_launcher.watchman
        fs_event_service = (
            FSEventService(
                watchman, scheduler=legacy_graph_scheduler.scheduler, build_root=build_root
            )
            if bootstrap_options.watchman_enable
            else None
        )

        invalidation_globs = OptionsInitializer.compute_pantsd_invalidation_globs(
            build_root, bootstrap_options,
        )

        scheduler_service = SchedulerService(
            fs_event_service=fs_event_service,
            legacy_graph_scheduler=legacy_graph_scheduler,
            build_root=build_root,
            invalidation_globs=invalidation_globs,
            pidfile=PantsDaemon.metadata_file_path(
                "pantsd", "pid", bootstrap_options.pants_subprocessdir
            ),
            pid=os.getpid(),
            max_memory_usage_in_bytes=bootstrap_options.pantsd_max_memory_usage,
        )

        store_gc_service = StoreGCService(legacy_graph_scheduler.scheduler)

        return PantsServices(
            services=tuple(
                service
                for service in (fs_event_service, scheduler_service, store_gc_service,)
                if service is not None
            ),
        )

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
        self._log_level = log_level
        self._server = server
        self._core = core
        self._bootstrap_options = bootstrap_options
        self._log_show_rust_3rdparty = (
            bootstrap_options.for_global_scope().log_show_rust_3rdparty
            if bootstrap_options
            else True
        )

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
    def _pantsd_logging(self) -> Iterator[IO[str]]:
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

        # Redirect stdio to /dev/null for the rest of the run, to reserve those file descriptors
        # for further forks.
        with stdio_as(stdin_fd=-1, stdout_fd=-1, stderr_fd=-1):
            # Reinitialize logging for the daemon context.
            init_rust_logger(self._log_level, self._log_show_rust_3rdparty)

            level = self._log_level
            ignores = self._bootstrap_options.for_global_scope().ignore_pants_warnings
            clear_logging_handlers()
            log_dir = os.path.join(self._work_dir, self.name)
            log_handler = setup_logging_to_file(
                level, log_dir=log_dir, log_filename=self.LOG_NAME, warnings_filter_regexes=ignores
            )

            self._native.override_thread_logging_destination_to_just_pantsd()

            # Do a python-level redirect of stdout/stderr, which will not disturb `0,1,2`.
            # TODO: Consider giving these pipes/actual fds, in order to make them "deep" replacements
            # for `1,2`, and allow them to be used via `stdio_as`.
            sys.stdout = _LoggerStream(logging.getLogger(), logging.INFO, log_handler)  # type: ignore[assignment]
            sys.stderr = _LoggerStream(logging.getLogger(), logging.WARN, log_handler)  # type: ignore[assignment]

            self._logger.debug("logging initialized")
            yield log_handler.stream

    def _write_nailgun_port(self):
        """Write the nailgun port to a well known file."""
        self.write_socket(self._server.port())

    def _initialize_pid(self):
        """Writes out our pid and metadata.

        Once written, does a one-time read of the pid to confirm that we haven't raced another
        process starting.
        """

        # Write the pidfile. The SchedulerService will monitor it after a grace period.
        pid = os.getpid()
        self.write_pid(pid=pid)
        self.write_metadata_by_name(
            "pantsd", self.FINGERPRINT_KEY, ensure_text(self.options_fingerprint)
        )

    def run_sync(self):
        """Synchronously run pantsd."""
        os.environ.pop("PYTHONPATH")

        # Switch log output to the daemon's log stream from here forward.
        self._close_stdio()
        with self._pantsd_logging() as log_stream:

            # We don't have any stdio streams to log to anymore, so we log to a file.
            # We don't override the faulthandler destination because the stream we get will proxy things
            # via the rust logging code, and faulthandler needs to be writing directly to a real file
            # descriptor. When pantsd logging was originally initialised, we already set up faulthandler
            # to log to the correct file descriptor, so don't override it.
            #
            # We can get tracebacks of the pantsd process by tailing the pantsd log and sending it
            # SIGUSR2.
            ExceptionSink.reset_interactive_output_stream(
                log_stream, override_faulthandler_destination=False,
            )

            # Reset the log location and the backtrace preference from the global bootstrap options.
            global_bootstrap_options = self._bootstrap_options.for_global_scope()
            ExceptionSink.reset_should_print_backtrace_to_terminal(
                global_bootstrap_options.print_exception_stacktrace
            )
            ExceptionSink.reset_log_location(global_bootstrap_options.pants_workdir)

            self._native.set_panic_handler()

            # Set the process name in ps output to 'pantsd' vs './pants compile src/etc:: -ldebug'.
            set_process_title(f"pantsd [{self._build_root}]")

            # Write our pid and the server's port to .pids. Order matters a bit here, because
            # technically all that is necessary to connect is the port, and Services are lazily
            # initialized by the core when a connection is established. Our pid needs to be on
            # disk before that happens.
            self._initialize_pid()
            self._write_nailgun_port()

            # Check periodically whether the core is valid, and exit if it is not.
            while self._core.is_valid():
                time.sleep(self.JOIN_TIMEOUT_SECONDS)

            # We're exiting: join the server to avoid interrupting ongoing runs.
            self._logger.info("waiting for ongoing runs to complete before exiting...")
            self._native.nailgun_server_await_shutdown(self._server)
            self._logger.info("exiting.")


def launch():
    """An external entrypoint that spawns a new pantsd instance."""
    PantsDaemon.create(OptionsBootstrapper.create()).run_sync()
