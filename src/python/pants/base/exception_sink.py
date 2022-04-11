# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import atexit
import datetime
import faulthandler
import logging
import os
import signal
import sys
import threading
import traceback
from contextlib import contextmanager
from typing import Callable, Dict, Iterator

import psutil
import setproctitle

from pants.util.dirutil import safe_mkdir, safe_open
from pants.util.osutil import Pid

logger = logging.getLogger(__name__)


class SignalHandler:
    """A specification for how to handle a fixed set of nonfatal signals.

    This is subclassed and registered with ExceptionSink.reset_signal_handler() whenever the signal
    handling behavior is modified for different pants processes, for example in the remote client when
    pantsd is enabled. The default behavior is to exit "gracefully" by leaving a detailed log of which
    signal was received, then exiting with failure.

    Note that the terminal will convert a ctrl-c from the user into a SIGINT.
    """

    @property
    def signal_handler_mapping(self) -> Dict[signal.Signals, Callable]:
        """A dict mapping (signal number) -> (a method handling the signal)."""
        # Could use an enum here, but we never end up doing any matching on the specific signal value,
        # instead just iterating over the registered signals to set handlers, so a dict is probably
        # better.
        return {
            signal.SIGINT: self._handle_sigint_if_enabled,
            signal.SIGQUIT: self.handle_sigquit,
            signal.SIGTERM: self.handle_sigterm,
        }

    def __init__(self, *, pantsd_instance: bool):
        self._ignore_sigint_lock = threading.Lock()
        self._ignoring_sigint = False
        self._pantsd_instance = pantsd_instance

    def _handle_sigint_if_enabled(self, signum: int, _frame):
        with self._ignore_sigint_lock:
            if not self._ignoring_sigint:
                self.handle_sigint(signum, _frame)

    def _toggle_ignoring_sigint(self, toggle: bool) -> None:
        if not self._pantsd_instance:
            with self._ignore_sigint_lock:
                self._ignoring_sigint = toggle

    def _send_signal_to_children(self, received_signal: int, signame: str) -> None:
        """Send a signal to any children of this process in order.

        Pants may have spawned multiple subprocesses via Python or Rust. Upon receiving a signal,
        this method is invoked to propagate the signal to all children, regardless of how they were
        spawned.
        """

        self_process = psutil.Process()
        children = self_process.children()
        logger.debug(f"Sending signal {signame} ({received_signal}) to child processes: {children}")
        for child_process in children:
            child_process.send_signal(received_signal)

    def handle_sigint(self, signum: int, _frame):
        self._send_signal_to_children(signum, "SIGINT")
        raise KeyboardInterrupt("User interrupted execution with control-c!")

    # TODO(#7406): figure out how to let sys.exit work in a signal handler instead of having to raise
    # this exception!
    class SignalHandledNonLocalExit(Exception):
        """Raised in handlers for non-fatal signals to overcome Python limitations.

        When waiting on a subprocess and in a signal handler, sys.exit appears to be ignored, and
        causes the signal handler to return. We want to (eventually) exit after these signals, not
        ignore them, so we raise this exception instead and check it in our sys.excepthook override.
        """

        def __init__(self, signum, signame):
            self.signum = signum
            self.signame = signame
            self.traceback_lines = traceback.format_stack()
            super(SignalHandler.SignalHandledNonLocalExit, self).__init__()

            if "I/O operation on closed file" in self.traceback_lines:
                logger.debug(
                    "SignalHandledNonLocalExit: unexpected appearance of "
                    "'I/O operation on closed file' in traceback"
                )

    def handle_sigquit(self, signum, _frame):
        self._send_signal_to_children(signum, "SIGQUIT")
        raise self.SignalHandledNonLocalExit(signum, "SIGQUIT")

    def handle_sigterm(self, signum, _frame):
        self._send_signal_to_children(signum, "SIGTERM")
        raise self.SignalHandledNonLocalExit(signum, "SIGTERM")


class ExceptionSink:
    """A mutable singleton object representing where exceptions should be logged to.

    The ExceptionSink should be installed in any process that is running Pants @rules via the
    engine. Notably, this does _not_ include the pantsd client, which does its own signal handling
    directly in order to forward information to the pantsd server.
    """

    # NB: see the bottom of this file where we call reset_log_location() and other mutators in order
    # to properly setup global state.
    _log_dir = None

    # Where to log stacktraces to in a SIGUSR2 handler.
    _interactive_output_stream = None

    # An instance of `SignalHandler` which is invoked to handle a static set of specific nonfatal
    # signals (these signal handlers are allowed to make pants exit, but unlike SIGSEGV they don't
    # need to exit immediately).
    _signal_handler: SignalHandler = SignalHandler(pantsd_instance=False)

    # These persistent open file descriptors are kept so the signal handler can do almost no work
    # (and lets faulthandler figure out signal safety).
    _pid_specific_error_fileobj = None
    _shared_error_fileobj = None

    def __new__(cls, *args, **kwargs):
        raise TypeError(
            "Instances of {} are not allowed to be constructed! Call install() instead.".format(
                cls.__name__
            )
        )

    class ExceptionSinkError(Exception):
        pass

    @classmethod
    def install(cls, log_location: str, pantsd_instance: bool) -> None:
        """Setup global state for this process, such as signal handlers and sys.excepthook."""

        # Set the log location for writing logs before bootstrap options are parsed.
        cls.reset_log_location(log_location)

        # NB: Mutate process-global state!
        sys.excepthook = ExceptionSink.log_exception

        # Setup a default signal handler.
        cls.reset_signal_handler(SignalHandler(pantsd_instance=pantsd_instance))

    # All reset_* methods are ~idempotent!
    @classmethod
    def reset_log_location(cls, new_log_location: str) -> None:
        """Re-acquire file handles to error logs based in the new location.

        Class state:
        - Overwrites `cls._log_dir`, `cls._pid_specific_error_fileobj`, and
          `cls._shared_error_fileobj`.
        OS state:
        - May create a new directory.
        - Overwrites signal handlers for many fatal and non-fatal signals (but not SIGUSR2).

        :raises: :class:`ExceptionSink.ExceptionSinkError` if the directory does not exist or is not
                 writable.
        """
        # We could no-op here if the log locations are the same, but there's no reason not to have the
        # additional safety of re-acquiring file descriptors each time (and erroring out early if the
        # location is no longer writable).
        try:
            safe_mkdir(new_log_location)
        except Exception as e:
            raise cls.ExceptionSinkError(
                "The provided log location path at '{}' is not writable or could not be created: {}.".format(
                    new_log_location, str(e)
                ),
                e,
            )

        pid = os.getpid()
        pid_specific_log_path = cls.exceptions_log_path(for_pid=pid, in_dir=new_log_location)
        shared_log_path = cls.exceptions_log_path(in_dir=new_log_location)
        assert pid_specific_log_path != shared_log_path
        try:
            pid_specific_error_stream = cls.open_pid_specific_error_stream(pid_specific_log_path)
            shared_error_stream = safe_open(shared_log_path, mode="a")
        except Exception as e:
            raise cls.ExceptionSinkError(
                "Error opening fatal error log streams for log location '{}': {}".format(
                    new_log_location, str(e)
                )
            )

        # NB: mutate process-global state!
        if faulthandler.is_enabled():
            logger.debug("re-enabling faulthandler")
            # Call Py_CLEAR() on the previous error stream:
            # https://github.com/vstinner/faulthandler/blob/master/faulthandler.c
            faulthandler.disable()
        # Send a stacktrace to this file if interrupted by a fatal error.
        faulthandler.enable(file=pid_specific_error_stream, all_threads=True)

        # NB: mutate the class variables!
        cls._log_dir = new_log_location
        cls._pid_specific_error_fileobj = pid_specific_error_stream
        cls._shared_error_fileobj = shared_error_stream

    @classmethod
    def open_pid_specific_error_stream(cls, path):
        ret = safe_open(path, mode="w")

        def unlink_if_empty():
            try:
                if os.path.getsize(path) == 0:
                    os.unlink(path)
            except OSError:
                pass

        # NB: This will only get called if nothing fatal happens, but that's precisely when we want
        # to get called. If anything fatal happens there should be an exception written to the log,
        # and therefore we don't want to unlink it.
        atexit.register(unlink_if_empty)
        return ret

    @classmethod
    def exceptions_log_path(cls, for_pid=None, in_dir=None):
        """Get the path to either the shared or pid-specific fatal errors log file."""
        if for_pid is None:
            intermediate_filename_component = ""
        else:
            assert isinstance(for_pid, Pid)
            intermediate_filename_component = f".{for_pid}"
        in_dir = in_dir or cls._log_dir
        return os.path.join(in_dir, f"exceptions{intermediate_filename_component}.log")

    @classmethod
    def _log_exception(cls, msg):
        """Try to log an error message to this process's error log and the shared error log.

        NB: Doesn't raise (logs an error instead).
        """
        pid = os.getpid()
        fatal_error_log_entry = cls._format_exception_message(msg, pid)

        # We care more about this log than the shared log, so write to it first.
        try:
            cls._try_write_with_flush(cls._pid_specific_error_fileobj, fatal_error_log_entry)
        except Exception as e:
            logger.error(
                "Error logging the message '{}' to the pid-specific file handle for {} at pid {}:\n{}".format(
                    msg, cls._log_dir, pid, e
                )
            )

        # Write to the shared log.
        try:
            # TODO: we should probably guard this against concurrent modification by other pants
            # subprocesses somehow.
            cls._try_write_with_flush(cls._shared_error_fileobj, fatal_error_log_entry)
        except Exception as e:
            logger.error(
                "Error logging the message '{}' to the shared file handle for {} at pid {}:\n{}".format(
                    msg, cls._log_dir, pid, e
                )
            )

    @classmethod
    def _try_write_with_flush(cls, fileobj, payload):
        """This method is here so that it can be patched to simulate write errors.

        This is because mock can't patch primitive objects like file objects.
        """
        fileobj.write(payload)
        fileobj.flush()

    @classmethod
    def reset_signal_handler(cls, signal_handler: SignalHandler) -> SignalHandler:
        """Given a SignalHandler, uses the `signal` std library functionality to set the pants
        process's signal handlers to those specified in the object.

        Note that since this calls `signal.signal()`, it will crash if not the main thread. Returns
        the previously-registered signal handler.
        """

        for signum, handler in signal_handler.signal_handler_mapping.items():
            signal.signal(signum, handler)
            # Retry any system calls interrupted by any of the signals we just installed handlers for
            # (instead of having them raise EINTR). siginterrupt(3) says this is the default behavior on
            # Linux and OSX.
            signal.siginterrupt(signum, False)

        previous_signal_handler = cls._signal_handler
        cls._signal_handler = signal_handler

        return previous_signal_handler

    @classmethod
    @contextmanager
    def trapped_signals(cls, new_signal_handler: SignalHandler) -> Iterator[None]:
        """A contextmanager which temporarily overrides signal handling.

        NB: This method calls signal.signal(), which will crash if not called from the main thread!
        """
        previous_signal_handler = cls.reset_signal_handler(new_signal_handler)
        try:
            yield
        finally:
            cls.reset_signal_handler(previous_signal_handler)

    @classmethod
    @contextmanager
    def ignoring_sigint(cls) -> Iterator[None]:
        """This method provides a context that temporarily disables responding to the SIGINT signal
        sent by a Ctrl-C in the terminal.

        We currently only use this to implement disabling catching SIGINT while an
        InteractiveProcess is running (where we want that process to catch it), and only when pantsd
        is not enabled (if pantsd is enabled, the client will actually catch SIGINT and forward it
        to the server, so we don't want the server process to ignore it.
        """

        try:
            cls._signal_handler._toggle_ignoring_sigint(True)
            yield
        finally:
            cls._signal_handler._toggle_ignoring_sigint(False)

    @classmethod
    def _iso_timestamp_for_now(cls):
        return datetime.datetime.now().isoformat()

    # NB: This includes a trailing newline, but no leading newline.
    _EXCEPTION_LOG_FORMAT = """\
timestamp: {timestamp}
process title: {process_title}
sys.argv: {args}
pid: {pid}
{message}
"""

    @classmethod
    def _format_exception_message(cls, msg, pid):
        return cls._EXCEPTION_LOG_FORMAT.format(
            timestamp=cls._iso_timestamp_for_now(),
            process_title=setproctitle.getproctitle(),
            args=sys.argv,
            pid=pid,
            message=msg,
        )

    _traceback_omitted_default_text = "(backtrace omitted)"

    @classmethod
    def _format_traceback(cls, traceback_lines, should_print_backtrace):
        if should_print_backtrace:
            traceback_string = "\n{}".format("".join(traceback_lines))
        else:
            traceback_string = f" {cls._traceback_omitted_default_text}"
        return traceback_string

    _UNHANDLED_EXCEPTION_LOG_FORMAT = """\
Exception caught: ({exception_type}){backtrace}
Exception message: {exception_message}{maybe_newline}
"""

    @classmethod
    def _format_unhandled_exception_log(cls, exc, tb, add_newline, should_print_backtrace):
        exc_type = type(exc)
        exception_full_name = f"{exc_type.__module__}.{exc_type.__name__}"
        exception_message = str(exc) if exc else "(no message)"
        maybe_newline = "\n" if add_newline else ""
        return cls._UNHANDLED_EXCEPTION_LOG_FORMAT.format(
            exception_type=exception_full_name,
            backtrace=cls._format_traceback(
                traceback_lines=traceback.format_tb(tb),
                should_print_backtrace=should_print_backtrace,
            ),
            exception_message=exception_message,
            maybe_newline=maybe_newline,
        )

    @classmethod
    def log_exception(cls, exc_class=None, exc=None, tb=None, add_newline=False):
        """Logs an unhandled exception to a variety of locations."""
        exc_class = exc_class or sys.exc_info()[0]
        exc = exc or sys.exc_info()[1]
        tb = tb or sys.exc_info()[2]

        # This exception was raised by a signal handler with the intent to exit the program.
        if exc_class == SignalHandler.SignalHandledNonLocalExit:
            return cls._handle_signal_gracefully(exc.signum, exc.signame, exc.traceback_lines)

        extra_err_msg = None
        try:
            # Always output the unhandled exception details into a log file, including the
            # traceback.
            exception_log_entry = cls._format_unhandled_exception_log(
                exc, tb, add_newline, should_print_backtrace=True
            )
            cls._log_exception(exception_log_entry)
        except Exception as e:
            extra_err_msg = f"Additional error logging unhandled exception {exc}: {e}"
            logger.error(extra_err_msg)

        # The rust logger implementation will have its own stacktrace, but at import time, we want
        # to be able to see any stacktrace to know where the error is being raised, so we reproduce
        # it here.
        exception_log_entry = cls._format_unhandled_exception_log(
            exc, tb, add_newline, should_print_backtrace=True
        )
        logger.exception(exception_log_entry)

    @classmethod
    def _handle_signal_gracefully(cls, signum, signame, traceback_lines):
        """Signal handler for non-fatal signals which raises or logs an error."""

        def gen_formatted(formatted_traceback: str) -> str:
            return f"Signal {signum} ({signame}) was raised. Exiting with failure.{formatted_traceback}"

        # Extract the stack, and format an entry to be written to the exception log.
        formatted_traceback = cls._format_traceback(
            traceback_lines=traceback_lines, should_print_backtrace=True
        )

        signal_error_log_entry = gen_formatted(formatted_traceback)

        # TODO: determine the appropriate signal-safe behavior here (to avoid writing to our file
        # descriptors reentrantly, which raises an IOError).
        # This method catches any exceptions raised within it.
        cls._log_exception(signal_error_log_entry)

        # Create a potentially-abbreviated traceback for the terminal or other interactive stream.
        formatted_traceback_for_terminal = cls._format_traceback(
            traceback_lines=traceback_lines,
            should_print_backtrace=True,
        )

        terminal_log_entry = gen_formatted(formatted_traceback_for_terminal)

        # Print the output via standard logging.
        logger.error(terminal_log_entry)
