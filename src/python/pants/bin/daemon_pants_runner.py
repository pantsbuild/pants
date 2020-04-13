# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import sys
import termios
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, List, Mapping, Optional

from pants.base.exception_sink import ExceptionSink
from pants.base.exiter import PANTS_FAILED_EXIT_CODE, PANTS_SUCCEEDED_EXIT_CODE, ExitCode, Exiter
from pants.bin.local_pants_runner import LocalPantsRunner
from pants.engine.rules import UnionMembership
from pants.help.help_printer import HelpPrinter
from pants.init.specs_calculator import SpecsCalculator
from pants.init.util import clean_global_runtime_state
from pants.java.nailgun_io import (
    NailgunStreamStdinReader,
    NailgunStreamWriterError,
    PipedNailgunStreamWriter,
)
from pants.java.nailgun_protocol import ChunkType, MaybeShutdownSocket, NailgunProtocol
from pants.option.options_bootstrapper import OptionsBootstrapper
from pants.pantsd.service.scheduler_service import SchedulerService
from pants.util.contextutil import hermetic_environment_as, stdio_as
from pants.util.socket import teardown_socket

logger = logging.getLogger(__name__)


class PantsRunFailCheckerExiter(Exiter):
    """Passed to pants runs triggered from this class, will raise an exception if the pants run
    failed."""

    def exit(self, result: ExitCode = 0, *args, **kwargs):
        if result != 0:
            raise _PantsRunFinishedWithFailureException(result)


class DaemonExiter(Exiter):
    """An Exiter that emits unhandled tracebacks and exit codes via the Nailgun protocol."""

    @classmethod
    @contextmanager
    def override_global_exiter(
        cls, maybe_shutdown_socket: MaybeShutdownSocket, finalizer: Callable[[], None],
    ) -> Iterator[None]:
        with ExceptionSink.exiter_as(
            lambda previous_exiter: cls(maybe_shutdown_socket, finalizer, previous_exiter)
        ):
            yield

    def __init__(
        self,
        maybe_shutdown_socket: MaybeShutdownSocket,
        finalizer: Callable[[], None],
        previous_exiter: Optional[Exiter],
    ) -> None:
        if previous_exiter:
            super().__init__(exiter=previous_exiter._exit)
        else:
            super().__init__()
        self._maybe_shutdown_socket = maybe_shutdown_socket
        self._finalizer = finalizer

    def exit(self, result: ExitCode = 0, msg: Optional[str] = None, *args, **kwargs):
        """Exit the runtime."""
        if self._finalizer:
            try:
                self._finalizer()
            except Exception as e:
                try:
                    with self._maybe_shutdown_socket.lock:
                        NailgunProtocol.send_stderr(
                            self._maybe_shutdown_socket.socket,
                            "\nUnexpected exception in finalizer: {!r}\n".format(e),
                        )
                except Exception:
                    pass

        with self._maybe_shutdown_socket.lock:
            # Write a final message to stderr if present.
            if msg:
                NailgunProtocol.send_stderr(self._maybe_shutdown_socket.socket, msg)

            # Send an Exit chunk with the result.
            # This will cause the client to disconnect from the socket.
            NailgunProtocol.send_exit_with_code(self._maybe_shutdown_socket.socket, result)

            # Shutdown the connected socket.
            teardown_socket(self._maybe_shutdown_socket.socket)
            self._maybe_shutdown_socket.is_shutdown = True


class _PantsRunFinishedWithFailureException(Exception):
    """Allows representing a pants run that failed for legitimate reasons (e.g. the target failed to
    compile).

    Will be raised by the exiter passed to LocalPantsRunner.
    """

    def __init__(self, exit_code: ExitCode = PANTS_FAILED_EXIT_CODE):
        """
        :param int exit_code: an optional exit code (defaults to PANTS_FAILED_EXIT_CODE)
        """
        super(_PantsRunFinishedWithFailureException, self).__init__(
            "Terminated with {}".format(exit_code)
        )

        if exit_code == PANTS_SUCCEEDED_EXIT_CODE:
            raise ValueError(
                "Cannot create {} with a successful exit code of {}".format(
                    type(self).__name__, PANTS_SUCCEEDED_EXIT_CODE
                )
            )

        self._exit_code = exit_code

    @property
    def exit_code(self) -> ExitCode:
        return self._exit_code


@dataclass(frozen=True)
class DaemonPantsRunner(ExceptionSink.AccessGlobalExiterMixin):
    """A daemonizing PantsRunner that speaks the nailgun protocol to a remote client.

    N.B. this class is primarily used by the PailgunService in pantsd.

    maybe_shutdown_socket: A connected socket capable of speaking the nailgun protocol.
    args: The arguments (i.e. sys.argv) for this run.
    env: The environment (i.e. os.environ) for this run.
    services: The PantsServices that are currently running.
    scheduler_service: The SchedulerService that holds the warm graph.
    """

    maybe_shutdown_socket: MaybeShutdownSocket
    args: List[str]
    env: Mapping[str, str]
    scheduler_service: SchedulerService

    @classmethod
    def create(cls, sock, args, env, scheduler_service):
        return cls(
            maybe_shutdown_socket=MaybeShutdownSocket(sock),
            args=args,
            env=env,
            scheduler_service=scheduler_service,
        )

    @classmethod
    @contextmanager
    def _tty_stdio(cls, env):
        """Handles stdio redirection in the case of all stdio descriptors being the same tty."""
        # If all stdio is a tty, there's only one logical I/O device (the tty device). This happens to
        # be addressable as a file in OSX and Linux, so we take advantage of that and directly open the
        # character device for output redirection - eliminating the need to directly marshall any
        # interactive stdio back/forth across the socket and permitting full, correct tty control with
        # no middle-man.
        stdin_ttyname, stdout_ttyname, stderr_ttyname = NailgunProtocol.ttynames_from_env(env)
        assert stdin_ttyname == stdout_ttyname == stderr_ttyname, (
            "expected all stdio ttys to be the same, but instead got: {}\n"
            "please file a bug at http://github.com/pantsbuild/pants".format(
                [stdin_ttyname, stdout_ttyname, stderr_ttyname]
            )
        )
        with open(stdin_ttyname, "rb+", 0) as tty:
            tty_fileno = tty.fileno()
            with stdio_as(stdin_fd=tty_fileno, stdout_fd=tty_fileno, stderr_fd=tty_fileno):

                def finalizer():
                    termios.tcdrain(tty_fileno)

                yield finalizer

    @classmethod
    @contextmanager
    def _pipe_stdio(
        cls, maybe_shutdown_socket, stdin_isatty, stdout_isatty, stderr_isatty, handle_stdin
    ):
        """Handles stdio redirection in the case of pipes and/or mixed pipes and ttys."""
        stdio_writers = ((ChunkType.STDOUT, stdout_isatty), (ChunkType.STDERR, stderr_isatty))
        types, ttys = zip(*(stdio_writers))

        @contextmanager
        def maybe_handle_stdin(want):
            if want:
                with NailgunStreamStdinReader.open(maybe_shutdown_socket, stdin_isatty) as fd:
                    yield fd
            else:
                with open("/dev/null", "rb") as fh:
                    yield fh.fileno()

        # TODO https://github.com/pantsbuild/pants/issues/7653
        with maybe_handle_stdin(handle_stdin) as stdin_fd, PipedNailgunStreamWriter.open_multi(
            maybe_shutdown_socket.socket, types, ttys
        ) as ((stdout_pipe, stderr_pipe), writer), stdio_as(
            stdout_fd=stdout_pipe.write_fd, stderr_fd=stderr_pipe.write_fd, stdin_fd=stdin_fd
        ):
            # N.B. This will be passed to and called by the `DaemonExiter` prior to sending an
            # exit chunk, to avoid any socket shutdown vs write races.
            stdout, stderr = sys.stdout, sys.stderr

            def finalizer():
                try:
                    stdout.flush()
                    stderr.flush()
                finally:
                    time.sleep(0.001)  # HACK: Sleep 1ms in the main thread to free the GIL.
                    stdout_pipe.stop_writing()
                    stderr_pipe.stop_writing()
                    writer.join(timeout=60)
                    if writer.isAlive():
                        raise NailgunStreamWriterError(
                            "pantsd timed out while waiting for the stdout/err to finish writing to the socket."
                        )

            yield finalizer

    @classmethod
    @contextmanager
    def nailgunned_stdio(cls, sock, env, handle_stdin=True):
        """Redirects stdio to the connected socket speaking the nailgun protocol."""
        # Determine output tty capabilities from the environment.
        stdin_isatty, stdout_isatty, stderr_isatty = NailgunProtocol.isatty_from_env(env)
        is_tty_capable = all((stdin_isatty, stdout_isatty, stderr_isatty))

        if is_tty_capable:
            with cls._tty_stdio(env) as finalizer:
                yield finalizer
        else:
            with cls._pipe_stdio(
                sock, stdin_isatty, stdout_isatty, stderr_isatty, handle_stdin
            ) as finalizer:
                yield finalizer

    def run(self):
        # Ensure anything referencing sys.argv inherits the Pailgun'd args.
        sys.argv = self.args

        # Invoke a Pants run with stdio redirected and a proxied environment.
        with self.nailgunned_stdio(
            self.maybe_shutdown_socket, self.env
        ) as finalizer, DaemonExiter.override_global_exiter(
            self.maybe_shutdown_socket, finalizer
        ), hermetic_environment_as(
            **self.env
        ):

            exit_code = PANTS_SUCCEEDED_EXIT_CODE
            try:
                # Clean global state.
                clean_global_runtime_state(reset_subsystem=True)

                options_bootstrapper = OptionsBootstrapper.create(args=self.args, env=self.env)
                options, build_config = LocalPantsRunner.parse_options(options_bootstrapper)

                global_options = options.for_global_scope()
                session = self.scheduler_service.prepare_graph(options)

                specs = SpecsCalculator.create(
                    options=options,
                    session=session.scheduler_session,
                    exclude_patterns=tuple(global_options.exclude_target_regexp),
                    tags=tuple(global_options.tag) if global_options.tag else (),
                )

                if options.help_request:
                    help_printer = HelpPrinter(
                        options=options,
                        union_membership=UnionMembership(build_config.union_rules()),
                    )
                    exit_code = help_printer.print_help()
                else:
                    exit_code = self.scheduler_service.graph_run_v2(
                        session, specs, options, options_bootstrapper
                    )

                # self.scheduler_service.graph_run_v2 will already run v2 or ambiguous goals. We should
                # only enter this code path if v1 is set.
                if global_options.v1:
                    with ExceptionSink.exiter_as_until_exception(
                        lambda _: PantsRunFailCheckerExiter()
                    ):
                        runner = LocalPantsRunner.create(
                            self.env, options_bootstrapper, specs, session
                        )

                        env_start_time = self.env.pop("PANTSD_RUNTRACKER_CLIENT_START_TIME", None)
                        start_time = float(env_start_time) if env_start_time else None
                        runner.set_start_time(start_time)
                        runner.run()

            except KeyboardInterrupt:
                self._exiter.exit_and_fail("Interrupted by user.\n")
            except _PantsRunFinishedWithFailureException as e:
                ExceptionSink.log_exception(
                    "Pants run failed with exception: {}; exiting".format(e)
                )
                self._exiter.exit(e.exit_code)
            except Exception as e:
                # TODO: We override sys.excepthook above when we call ExceptionSink.set_exiter(). That
                # excepthook catches `SignalHandledNonLocalExit`s from signal handlers, which isn't
                # happening here, so something is probably overriding the excepthook. By catching Exception
                # and calling this method, we emulate the normal, expected sys.excepthook override.
                ExceptionSink._log_unhandled_exception_and_exit(exc=e)
            else:
                self._exiter.exit(exit_code)
