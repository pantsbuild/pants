# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import datetime
import faulthandler
import logging
import os
import signal
import sys
import threading
import traceback
from builtins import object, str
from contextlib import contextmanager

import setproctitle
from future.utils import PY3

from pants.base.exiter import Exiter
from pants.util.dirutil import safe_mkdir, safe_open
from pants.util.osutil import IntegerForPid


logger = logging.getLogger(__name__)


class SignalHandler(object):
  """A specification for how to handle a fixed set of nonfatal signals.

  This is subclassed and registered with ExceptionSink.reset_signal_handler() whenever the signal
  handling behavior is modified for different pants processes, for example in the remote client when
  pantsd is enabled. The default behavior is to exit "gracefully" by leaving a detailed log of which
  signal was received, then exiting with failure.

  Note that the terminal will convert a ctrl-c from the user into a SIGINT.
  """

  @property
  def signal_handler_mapping(self):
    """A dict mapping (signal number) -> (a method handling the signal)."""
    # Could use an enum here, but we never end up doing any matching on the specific signal value,
    # instead just iterating over the registered signals to set handlers, so a dict is probably
    # better.
    return {
      signal.SIGINT: self._handle_sigint_if_enabled,
      signal.SIGQUIT: self.handle_sigquit,
      signal.SIGTERM: self.handle_sigterm,
    }

  def __init__(self):
    self._ignore_sigint_lock = threading.Lock()
    self._threads_ignoring_sigint = 0

  def _check_sigint_gate_is_correct(self):
    assert self._threads_ignoring_sigint >= 0, \
      "This should never happen, someone must have modified the counter outside of SignalHandler."

  def _handle_sigint_if_enabled(self, signum, _frame):
    with self._ignore_sigint_lock:
      self._check_sigint_gate_is_correct()
      threads_ignoring_sigint = self._threads_ignoring_sigint
    if threads_ignoring_sigint == 0:
      self.handle_sigint(signum, _frame)

  @contextmanager
  def _ignoring_sigint(self):
    with self._ignore_sigint_lock:
      self._check_sigint_gate_is_correct()
      self._threads_ignoring_sigint += 1
    try:
      yield
    finally:
      with self._ignore_sigint_lock:
        self._threads_ignoring_sigint -= 1
        self._check_sigint_gate_is_correct()

  def handle_sigint(self, signum, _frame):
    raise KeyboardInterrupt('User interrupted execution with control-c!')

  # TODO(#7406): figure out how to let sys.exit work in a signal handler instead of having to raise
  # this exception!
  class SignalHandledNonLocalExit(Exception):
    """Raised in handlers for non-fatal signals to overcome Python limitations.

    When waiting on a subprocess and in a signal handler, sys.exit appears to be ignored, and causes
    the signal handler to return. We want to (eventually) exit after these signals, not ignore them,
    so we raise this exception instead and check it in our sys.excepthook override.
    """

    def __init__(self, signum, signame):
      self.signum = signum
      self.signame = signame
      self.traceback_lines = traceback.format_stack()
      super(SignalHandler.SignalHandledNonLocalExit, self).__init__()

  def handle_sigquit(self, signum, _frame):
    raise self.SignalHandledNonLocalExit(signum, 'SIGQUIT')

  def handle_sigterm(self, signum, _frame):
    raise self.SignalHandledNonLocalExit(signum, 'SIGTERM')


class ExceptionSink(object):
  """A mutable singleton object representing where exceptions should be logged to."""

  # NB: see the bottom of this file where we call reset_log_location() and other mutators in order
  # to properly setup global state.
  _log_dir = None
  # We need an exiter in order to know what to do after we log a fatal exception or handle a
  # catchable signal.
  _exiter = None
  # Where to log stacktraces to in a SIGUSR2 handler.
  _interactive_output_stream = None
  # Whether to print a stacktrace in any fatal error message printed to the terminal.
  _should_print_backtrace_to_terminal = True
  # An instance of `SignalHandler` which is invoked to handle a static set of specific
  # nonfatal signals (these signal handlers are allowed to make pants exit, but unlike SIGSEGV they
  # don't need to exit immediately).
  _signal_handler = None

  # These persistent open file descriptors are kept so the signal handler can do almost no work
  # (and lets faulthandler figure out signal safety).
  _pid_specific_error_fileobj = None
  _shared_error_fileobj = None

  def __new__(cls, *args, **kwargs):
    raise TypeError('Instances of {} are not allowed to be constructed!'
                    .format(cls.__name__))

  class ExceptionSinkError(Exception): pass

  @classmethod
  def reset_should_print_backtrace_to_terminal(cls, should_print_backtrace):
    """Set whether a backtrace gets printed to the terminal error stream on a fatal error.

    Class state:
    - Overwrites `cls._should_print_backtrace_to_terminal`.
    """
    cls._should_print_backtrace_to_terminal = should_print_backtrace

  # All reset_* methods are ~idempotent!
  @classmethod
  def reset_log_location(cls, new_log_location):
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

    # Create the directory if possible, or raise if not writable.
    cls._check_or_create_new_destination(new_log_location)

    pid_specific_error_stream, shared_error_stream = cls._recapture_fatal_error_log_streams(
      new_log_location)

    # NB: mutate process-global state!
    if faulthandler.is_enabled():
      logger.debug('re-enabling faulthandler')
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
  def reset_exiter(cls, exiter):
    """
    Class state:
    - Overwrites `cls._exiter`.
    Python state:
    - Overwrites sys.excepthook.
    """
    assert(isinstance(exiter, Exiter))
    # NB: mutate the class variables! This is done before mutating the exception hook, because the
    # uncaught exception handler uses cls._exiter to exit.
    cls._exiter = exiter
    # NB: mutate process-global state!
    sys.excepthook = cls._log_unhandled_exception_and_exit

  @classmethod
  def reset_interactive_output_stream(
    cls,
    interactive_output_stream,
    override_faulthandler_destination=True
  ):
    """
    Class state:
    - Overwrites `cls._interactive_output_stream`.
    OS state:
    - Overwrites the SIGUSR2 handler.

    This method registers a SIGUSR2 handler, which permits a non-fatal `kill -31 <pants pid>` for
    stacktrace retrieval. This is also where the the error message on fatal exit will be printed to.
    """
    try:
      # NB: mutate process-global state!
      # This permits a non-fatal `kill -31 <pants pid>` for stacktrace retrieval.
      if override_faulthandler_destination:
        faulthandler.register(signal.SIGUSR2, interactive_output_stream,
                              all_threads=True, chain=False)
      # NB: mutate the class variables!
      cls._interactive_output_stream = interactive_output_stream
    except ValueError:
      # Warn about "ValueError: IO on closed file" when the stream is closed.
      cls.log_exception(
        "Cannot reset interactive_output_stream -- stream (probably stderr) is closed")

  @classmethod
  def exceptions_log_path(cls, for_pid=None, in_dir=None):
    """Get the path to either the shared or pid-specific fatal errors log file."""
    if for_pid is None:
      intermediate_filename_component = ''
    else:
      assert(isinstance(for_pid, IntegerForPid))
      intermediate_filename_component = '.{}'.format(for_pid)
    in_dir = in_dir or cls._log_dir
    return os.path.join(
      in_dir,
      'logs',
      'exceptions{}.log'.format(intermediate_filename_component))

  @classmethod
  def log_exception(cls, msg):
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
        "Error logging the message '{}' to the pid-specific file handle for {} at pid {}:\n{}"
        .format(msg, cls._log_dir, pid, e))

    # Write to the shared log.
    try:
      # TODO: we should probably guard this against concurrent modification by other pants
      # subprocesses somehow.
      cls._try_write_with_flush(cls._shared_error_fileobj, fatal_error_log_entry)
    except Exception as e:
      logger.error(
        "Error logging the message '{}' to the shared file handle for {} at pid {}:\n{}"
        .format(msg, cls._log_dir, pid, e))

  @classmethod
  def _try_write_with_flush(cls, fileobj, payload):
    """This method is here so that it can be patched to simulate write errors.

    This is because mock can't patch primitive objects like file objects.
    """
    fileobj.write(payload)
    fileobj.flush()

  @classmethod
  def _check_or_create_new_destination(cls, destination):
    try:
      safe_mkdir(destination)
    except Exception as e:
      raise cls.ExceptionSinkError(
        "The provided exception sink path at '{}' is not writable or could not be created: {}."
        .format(destination, str(e)),
        e)

  @classmethod
  def _recapture_fatal_error_log_streams(cls, new_log_location):
    # NB: We do not close old file descriptors under the assumption their lifetimes are managed
    # elsewhere.
    # We recapture both log streams each time.
    pid = os.getpid()
    pid_specific_log_path = cls.exceptions_log_path(for_pid=pid, in_dir=new_log_location)
    shared_log_path = cls.exceptions_log_path(in_dir=new_log_location)
    assert(pid_specific_log_path != shared_log_path)
    try:
      # Truncate the pid-specific error log file.
      pid_specific_error_stream = safe_open(pid_specific_log_path, mode='w')
      # Append to the shared error file.
      shared_error_stream = safe_open(shared_log_path, mode='a')
    except Exception as e:
      raise cls.ExceptionSinkError(
        "Error opening fatal error log streams for log location '{}': {}"
        .format(new_log_location, str(e)))

    return (pid_specific_error_stream, shared_error_stream)

  @classmethod
  def reset_signal_handler(cls, signal_handler):
    """
    Class state:
    - Overwrites `cls._signal_handler`.
    OS state:
    - Overwrites signal handlers for SIGINT, SIGQUIT, and SIGTERM.

    NB: This method calls signal.signal(), which will crash if not called from the main thread!

    :returns: The :class:`SignalHandler` that was previously registered, or None if this is
              the first time this method was called.
    """
    assert(isinstance(signal_handler, SignalHandler))
    # NB: Modify process-global state!
    for signum, handler in signal_handler.signal_handler_mapping.items():
      signal.signal(signum, handler)
      # Retry any system calls interrupted by any of the signals we just installed handlers for
      # (instead of having them raise EINTR). siginterrupt(3) says this is the default behavior on
      # Linux and OSX.
      signal.siginterrupt(signum, False)

    previous_signal_handler = cls._signal_handler
    # NB: Mutate the class variables!
    cls._signal_handler = signal_handler
    return previous_signal_handler

  @classmethod
  @contextmanager
  def trapped_signals(cls, new_signal_handler):
    """
    A contextmanager which temporarily overrides signal handling.

    NB: This method calls signal.signal(), which will crash if not called from the main thread!
    """
    try:
      previous_signal_handler = cls.reset_signal_handler(new_signal_handler)
      yield
    finally:
      cls.reset_signal_handler(previous_signal_handler)

  @classmethod
  @contextmanager
  def ignoring_sigint(cls):
    """
    A contextmanager which disables handling sigint in the current signal handler.
    This allows threads that are not the main thread to ignore sigint.

    NB: Only use this if you can't use ExceptionSink.trapped_signals().

    Class state:
    - Toggles `self._ignore_sigint` in `cls._signal_handler`.
    """
    with cls._signal_handler._ignoring_sigint():
      yield

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
      message=msg)

  _traceback_omitted_default_text = '(backtrace omitted)'

  @classmethod
  def _format_traceback(cls, traceback_lines, should_print_backtrace):
    if should_print_backtrace:
      traceback_string = '\n{}'.format(''.join(traceback_lines))
    else:
      traceback_string = ' {}'.format(cls._traceback_omitted_default_text)
    return traceback_string

  _UNHANDLED_EXCEPTION_LOG_FORMAT = """\
Exception caught: ({exception_type}){backtrace}
Exception message: {exception_message}{maybe_newline}
"""

  @classmethod
  def _format_unhandled_exception_log(cls, exc, tb, add_newline, should_print_backtrace):
    exc_type = type(exc)
    exception_full_name = '{}.{}'.format(exc_type.__module__, exc_type.__name__)
    exception_message = str(exc) if exc else '(no message)'
    maybe_newline = '\n' if add_newline else ''
    return cls._UNHANDLED_EXCEPTION_LOG_FORMAT.format(
      exception_type=exception_full_name,
      backtrace=cls._format_traceback(traceback_lines=traceback.format_tb(tb),
                                      should_print_backtrace=should_print_backtrace),
      exception_message=exception_message,
      maybe_newline=maybe_newline)

  _EXIT_FAILURE_TERMINAL_MESSAGE_FORMAT = """\
timestamp: {timestamp}
{terminal_msg}
"""

  @classmethod
  def _exit_with_failure(cls, terminal_msg):
    formatted_terminal_msg = cls._EXIT_FAILURE_TERMINAL_MESSAGE_FORMAT.format(
      timestamp=cls._iso_timestamp_for_now(),
      terminal_msg=terminal_msg or '<no exit reason provided>')
    # Exit with failure, printing a message to the terminal (or whatever the interactive stream is).
    cls._exiter.exit_and_fail(msg=formatted_terminal_msg, out=cls._interactive_output_stream)

  @classmethod
  def _log_unhandled_exception_and_exit(cls, exc_class=None, exc=None, tb=None, add_newline=False):
    """A sys.excepthook implementation which logs the error and exits with failure."""
    exc_class = exc_class or sys.exc_info()[0]
    exc = exc or sys.exc_info()[1]
    tb = tb or sys.exc_info()[2]

    # This exception was raised by a signal handler with the intent to exit the program.
    if exc_class == SignalHandler.SignalHandledNonLocalExit:
      return cls._handle_signal_gracefully(exc.signum, exc.signame, exc.traceback_lines)

    extra_err_msg = None
    try:
      # Always output the unhandled exception details into a log file, including the traceback.
      exception_log_entry = cls._format_unhandled_exception_log(exc, tb, add_newline,
                                                                should_print_backtrace=True)
      cls.log_exception(exception_log_entry)
    except Exception as e:
      extra_err_msg = 'Additional error logging unhandled exception {}: {}'.format(exc, e)
      logger.error(extra_err_msg)

    # Generate an unhandled exception report fit to be printed to the terminal (respecting the
    # Exiter's should_print_backtrace field).
    stderr_printed_error = cls._format_unhandled_exception_log(
      exc, tb, add_newline,
      should_print_backtrace=cls._should_print_backtrace_to_terminal)
    if extra_err_msg:
      stderr_printed_error = '{}\n{}'.format(stderr_printed_error, extra_err_msg)
    cls._exit_with_failure(stderr_printed_error)

  _CATCHABLE_SIGNAL_ERROR_LOG_FORMAT = """\
Signal {signum} ({signame}) was raised. Exiting with failure.{formatted_traceback}
"""

  @classmethod
  def _handle_signal_gracefully(cls, signum, signame, traceback_lines):
    """Signal handler for non-fatal signals which raises or logs an error and exits with failure."""
    # Extract the stack, and format an entry to be written to the exception log.
    formatted_traceback = cls._format_traceback(traceback_lines=traceback_lines,
                                                should_print_backtrace=True)
    signal_error_log_entry = cls._CATCHABLE_SIGNAL_ERROR_LOG_FORMAT.format(
      signum=signum,
      signame=signame,
      formatted_traceback=formatted_traceback)
    # TODO: determine the appropriate signal-safe behavior here (to avoid writing to our file
    # descriptors re-entrantly, which raises an IOError).
    # This method catches any exceptions raised within it.
    cls.log_exception(signal_error_log_entry)

    # Create a potentially-abbreviated traceback for the terminal or other interactive stream.
    formatted_traceback_for_terminal = cls._format_traceback(
      traceback_lines=traceback_lines,
      should_print_backtrace=cls._should_print_backtrace_to_terminal)
    terminal_log_entry = cls._CATCHABLE_SIGNAL_ERROR_LOG_FORMAT.format(
      signum=signum,
      signame=signame,
      formatted_traceback=formatted_traceback_for_terminal)
    # Exit, printing the output to the terminal.
    cls._exit_with_failure(terminal_log_entry)


# Setup global state such as signal handlers and sys.excepthook with probably-safe values at module
# import time.
# TODO: add testing for fatal errors at import-time, which may occur if there are errors in plugins.
# Set the initial log location, for fatal errors during import time.
ExceptionSink.reset_log_location(os.path.join(os.getcwd(), '.pants.d'))
# Sets except hook for exceptions at import time.
ExceptionSink.reset_exiter(Exiter(exiter=sys.exit))
# Sets a SIGUSR2 handler.
ExceptionSink.reset_interactive_output_stream(sys.stderr.buffer if PY3 else sys.stderr)
# Sets a handler that logs nonfatal signals to the exception sink before exiting.
ExceptionSink.reset_signal_handler(SignalHandler())
# Set whether to print stacktraces on exceptions or signals during import time.
# NB: This will be overridden by bootstrap options in PantsRunner, so we avoid printing out a full
# stacktrace when a user presses control-c during import time unless the environment variable is set
# to explicitly request it. The exception log will have any stacktraces regardless so this should
# not hamper debugging.
ExceptionSink.reset_should_print_backtrace_to_terminal(
  should_print_backtrace=os.environ.get('PANTS_PRINT_EXCEPTION_STACKTRACE') == 'True')
