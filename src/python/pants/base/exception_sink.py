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
import traceback
from builtins import object, str

from future.utils import binary_type

from pants.base.exiter import Exiter
from pants.util.dirutil import safe_mkdir, safe_open
from pants.util.memo import memoized_property
from pants.util.objects import Exactly, datatype


logger = logging.getLogger(__name__)


class GetLogLocationRequest(datatype([
    ('pid', Exactly(int, long, type(None))),
    ('log_dir', Exactly(binary_type, type(None))),
])):

  # TODO: link the datatype default values ticket!
  def __new__(cls, pid=None, log_dir=None):
    if log_dir is not None:
      log_dir = binary_type(log_dir)
    return super(GetLogLocationRequest, cls).__new__(cls, log_dir=log_dir, pid=pid)


class LogLocation(datatype([
    ('pid', Exactly(int, long)),
    ('log_dir', Exactly(binary_type, type(None))),
])):

  # TODO: link the datatype default values ticket!
  def __new__(cls, pid, log_dir=None):
    if log_dir is not None:
      log_dir = binary_type(log_dir)
    return super(LogLocation, cls).__new__(cls, pid=pid, log_dir=log_dir)

  @memoized_property
  def as_request(self):
    return GetLogLocationRequest(pid=self.pid, log_dir=self.log_dir)

  @classmethod
  def from_options_for_current_process(cls, options):
    """???"""
    return cls(pid=os.getpid(), log_dir=options.pants_workdir)


class ExceptionSink(object):
  """A mutable singleton object representing where exceptions should be logged to."""

  # TODO: see the bottom of this file where we call reset_log_location() and friends in order to
  # properly setup global state.
  _log_location = None
  # We need an exiter in order to know what to do after we log a fatal exception.
  _exiter = None
  # Where to log stacktraces to in a SIGUSR2 handler.
  _interactive_output_stream = None

  # NB: These file descriptors are kept under the assumption that pants won't randomly close them
  # later -- we want the signal handler to be able to do no work (and to let faulthandler figure out
  # signal safety).
  _pid_specific_error_fileobj = None
  _shared_error_fileobj = None

  # Integer code to exit with on an unhandled exception.
  UNHANDLED_EXCEPTION_EXIT_CODE = 1

  # faulthandler.enable() installs handlers for SIGSEGV, SIGFPE, SIGABRT, SIGBUS and SIGILL, but we
  # also want to dump a traceback when receiving these other usually-fatal signals.
  GRACEFULLY_HANDLED_SIGNALS = [
    signal.SIGTERM,
  ]

  # These signals are converted into a KeyboardInterrupt exception.
  KEYBOARD_INTERRUPT_SIGNALS = [
    signal.SIGINT,
    signal.SIGQUIT,
  ]

  def __new__(cls, *args, **kwargs):
    raise TypeError('Instances of {} are not allowed to be constructed!'
                    .format(cls.__name__))

  class ExceptionSinkError(Exception): pass

  # TODO: ensure all set_* methods are idempotent!
  @classmethod
  def reset_log_location(cls, new_log_location):
    """
    Class state:
    - Will leak the old file handles without closing them.
    OS state:
    - May create a new directory.
    - May raise ExceptionSinkError if the directory is not writable.
    - Will register signal handlers for fatal handlers (clobbering old values).
    """
    # TODO: check for noop on both of the arguments!
    if new_log_location.log_dir is None:
      if new_log_location.pid is None:
        raise cls.ExceptionSinkError(
          "No-op call to reset_new_log_location(): argument was {!r}."
          .format(new_log_location))
    else:
      # Ensure the directory is suitable for writing to, or raise.
      cls._check_or_create_new_destination(new_log_location.log_dir)
    if new_log_location.pid is None:
      new_log_location = new_log_location.copy(pid=os.getpid())

    pid_specific_error_stream, shared_error_stream = cls._recapture_fatal_error_log_streams(
      new_log_location)

    # NB: mutate process-global state!
    if faulthandler.is_enabled():
      faulthandler.disable()
    # Send a stacktrace to this file if interrupted by a fatal error.
    faulthandler.enable(file=pid_specific_error_stream, all_threads=True)
    # Log a timestamped exception and exit gracefully on non-fatal signals.
    # TODO: ascertain whether the the signal handler method used here is signal-safe for our
    # purposes.
    all_handled_signals = cls.GRACEFULLY_HANDLED_SIGNALS + cls.KEYBOARD_INTERRUPT_SIGNALS
    for signum in all_handled_signals:
      signal.signal(signum, cls.handle_signal_gracefully)

    # NB: mutate the class variables!
    cls._log_location = new_log_location
    cls._pid_specific_error_fileobj = pid_specific_error_stream
    cls._shared_error_fileobj = shared_error_stream

  @classmethod
  def reset_exiter(cls, exiter):
    """
    Class state:
    - Will leak the old Exiter instance.
    Python state:
    - Will register sys.excepthook, clobbering any previous value.
    """
    assert(isinstance(exiter, Exiter))
    # NB: mutate the class variables! This is done before mutating the exception hook, because the
    # uncaught exception handler uses cls._exiter to exit.
    cls._exiter = exiter
    # NB: mutate process-global state!
    sys.excepthook = cls._log_unhandled_exception_and_exit

  @classmethod
  def reset_interactive_output_stream(cls, interactive_output_stream):
    """
    Class state:
    - Will leak the old output stream.
    OS state:
    - Will register a handler for SIGUSR2, clobbering any previous value.
    """
    # TODO: chain=True will log tracebacks to previous values of the trace stream as well -- what
    # happens if those file objects are eventually closed? Does faulthandler just ignore them?
    # This permits a non-fatal `kill -31 <pants pid>` for stacktrace retrieval.
    # NB: mutate process-global state!
    faulthandler.register(signal.SIGUSR2, interactive_output_stream, chain=True)
    # We don't *necessarily* need to keep a reference to this, but we do here for clarity.
    # NB: mutate the class variables!
    cls._interactive_output_stream = interactive_output_stream

  @classmethod
  def exceptions_log_path(cls, get_log_location_request):
    if get_log_location_request.pid is None:
      intermediate_filename_component = ''
    else:
      intermediate_filename_component = '.{}'.format(get_log_location_request.pid)
    in_dir = get_log_location_request.log_dir or cls._log_location.log_dir
    return os.path.join(
      in_dir,
      'logs',
      'exceptions{}.log'.format(intermediate_filename_component))

  @classmethod
  def _try_write_with_flush(cls, fileobj, payload):
    # The attribute 'closed' may not be on all file objects, see:
    # https://docs.python.org/2.4/lib/bltin-file-objects.html
    is_probably_writable = not getattr(fileobj, 'closed', False)
    if not is_probably_writable:
      raise cls.ExceptionSinkError(
        "Attempted write to closed filebj {}:\n{}"
        .format(fileobj, payload))
    else:
      fileobj.write(payload)
      fileobj.flush()

  @classmethod
  def log_exception(cls, msg):
    """

    NB: Doesn't raise.
    """

    fatal_error_log_entry = cls._format_exception_message(msg, cls._log_location.pid)

    # We care more about this log than the shared log, so write to it first.
    try:
      cls._try_write_with_flush(cls._pid_specific_error_fileobj, fatal_error_log_entry)
    except Exception as e:
      logger.error(
        "Error logging the message '{}' to the pid-specific file handle for {}:\n{}"
        .format(msg, cls._log_location, e))

    # Write to the shared log.
    try:
      # TODO: we should probably guard this against concurrent modification by other pants
      # subprocesses somehow.
      cls._try_write_with_flush(cls._shared_error_fileobj, fatal_error_log_entry)
    except Exception as e:
      logger.error(
        "Error logging the message '{}' to the shared file handle for {}:\n{}"
        .format(msg, cls._log_location, e))

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
  def _recapture_fatal_error_log_streams(cls, log_location):
    # NB: We do not close old file descriptors! This is bounded by the number of times any method is
    # called, which should be few and finite.
    # We recapture both log streams each time.
    # NB: We truncate the pid-specific error log file.
    pid_specific_log_path = cls.exceptions_log_path(log_location.as_request)
    shared_log_path = cls.exceptions_log_path(log_location.as_request.copy(pid=None))
    assert(pid_specific_log_path != shared_log_path)
    try:
      pid_specific_error_stream = safe_open(pid_specific_log_path, mode='w')
      shared_error_stream = safe_open(shared_log_path, mode='a')
    except Exception as e:
      raise cls.ExceptionSinkError(
        "Error opening fatal error log streams for log location {!r}: {}"
        .format(log_location, str(e)))

    # TODO: determine whether any further validation of the streams (try writing to them here?) is
    # useful/necessary for faulthandler (it seems it just doesn't write to e.g. closed file
    # descriptors, so probably not).
    return (pid_specific_error_stream, shared_error_stream)

  @classmethod
  def _iso_timestamp_for_now(cls):
    return datetime.datetime.now().isoformat()

  # NB: This includes a trailing newline, but no leading newline.
  _EXCEPTION_LOG_FORMAT = """\
timestamp: {timestamp}
args: {args}
pid: {pid}
{message}
"""

  @classmethod
  def _format_exception_message(cls, msg, pid):
    return cls._EXCEPTION_LOG_FORMAT.format(
      timestamp=cls._iso_timestamp_for_now(),
      args=sys.argv,
      pid=pid,
      message=msg)

  _traceback_omitted_default_text = '(backtrace omitted)'

  @classmethod
  def _format_traceback(cls, tb, should_print_backtrace):
    if should_print_backtrace:
      traceback_string = ''.join(traceback.format_tb(tb))
    else:
      traceback_string = cls._traceback_omitted_default_text
    return traceback_string

  _UNHANDLED_EXCEPTION_LOG_FORMAT = """\
Exception caught: ({exception_type})
{backtrace}
Exception message: {exception_message}{maybe_newline}
"""

  @classmethod
  def _format_unhandled_exception_log(cls, exc, tb, add_newline, should_print_backtrace):
    exception_message = str(exc) if exc else '(no message)'
    maybe_newline = '\n' if add_newline else ''
    return cls._UNHANDLED_EXCEPTION_LOG_FORMAT.format(
      exception_type=type(exc),
      backtrace=cls._format_traceback(tb, should_print_backtrace=should_print_backtrace),
      exception_message=exception_message,
      maybe_newline=maybe_newline)

  @classmethod
  def _exit_with_failure(cls, terminal_msg):
    # Exit with failure, printing a message to the terminal (or whatever the interactive stream is).
    cls._exiter.exit(result=cls.UNHANDLED_EXCEPTION_EXIT_CODE,
                     msg=terminal_msg,
                     out=cls._interactive_output_stream)

  @classmethod
  def _log_unhandled_exception_and_exit(cls, exc_class=None, exc=None, tb=None, add_newline=False):
    """Default sys.excepthook implementation for unhandled exceptions."""
    exc_class = exc_class or sys.exc_info()[0]
    exc = exc or sys.exc_info()[1]
    tb = tb or sys.exc_info()[2]

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
    # Exiter's _should_print_backtrace field).
    # TODO: the Exiter just prints to stderr -- is that always open? Should we manage that here too?
    stderr_printed_error = cls._format_unhandled_exception_log(
      exc, tb, add_newline,
      should_print_backtrace=cls._exiter.should_print_backtrace)
    if extra_err_msg:
      stderr_printed_error = '{}\n{}'.format(stderr_printed_error, extra_err_msg)
    cls._exit_with_failure(stderr_printed_error)

  _CATCHABLE_SIGNAL_ERROR_LOG_FORMAT = """\
Signal {signum} was raised. Exiting with failure.
{formatted_traceback}
"""

  _is_handling_signal = False

  @classmethod
  def handle_signal_gracefully(cls, signum, frame):
    if signum in cls.KEYBOARD_INTERRUPT_SIGNALS:
      raise KeyboardInterrupt('User interrupted execution with control-c!')
    # TODO: determine the appropriate signal-safe behavior here (to avoid writing to our file
    # descriptors re-entrantly, which raises an IOError). This is a best-effort solution.
    if cls._is_handling_signal:
      return
    cls._is_handling_signal = True
    tb = frame.f_exc_traceback
    should_print_backtrace = tb is not None
    formatted_traceback = cls._format_traceback(tb, should_print_backtrace=should_print_backtrace)
    signal_error_log_entry = cls._CATCHABLE_SIGNAL_ERROR_LOG_FORMAT.format(
      signum=signum,
      formatted_traceback=formatted_traceback)
    # This method catches any exceptions raised within it.
    cls.log_exception(signal_error_log_entry)
    # NB: We always print the traceback to the terminal in this case.
    cls._exit_with_failure(signal_error_log_entry)


# Setup global state such as signal handlers and sys.excepthook with probably-safe values at module
# import time.
# Sets fatal signal handlers with reasonable defaults to catch errors early in startup.
ExceptionSink.reset_log_location(LogLocation(pid=os.getpid(), log_dir=os.getcwd()))
# Sets except hook.
ExceptionSink.reset_exiter(Exiter(print_backtraces=True))
# Sets a SIGUSR2 handler.
ExceptionSink.reset_interactive_output_stream(sys.stderr)
