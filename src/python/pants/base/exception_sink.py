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
from pants.util.objects import Exactly, datatype


logger = logging.getLogger(__name__)


class LogLocation(datatype([
    ('log_dir', Exactly(binary_type, type(None))),
    ('pid', Exactly(int, long, type(None))),
])):

  # TODO: link the datatype default values ticket!
  def __new__(cls, log_dir=None, pid=None):
    if log_dir is not None:
      log_dir = binary_type(log_dir)
    return super(LogLocation, cls).__new__(cls, log_dir=log_dir, pid=pid)

  @classmethod
  def from_options_for_current_process(cls, options):
    return cls(log_dir=options.pants_workdir, pid=os.getpid())


class ExceptionSink(object):
  """A mutable singleton object representing where exceptions should be logged to."""

  # TODO: see the bottom of this file where we call reset_log_location() and friends in order to
  # properly setup global state.
  # TODO: document all of these fields!
  _log_dir = None
  _pid = None
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

  def __new__(cls, *args, **kwargs):
    raise TypeError('Instances of {} are not allowed to be constructed!'
                    .format(cls.__name__))

  class ExceptionSinkError(Exception): pass

  # TODO: ensure all set_* methods are idempotent!
  @classmethod
  def reset_log_location(cls, log_location_request):
    """
    Class state:
    - Will leak the old file handles without closing them.
    OS state:
    - May create a new directory.
    - May raise ExceptionSinkError if the directory is not writable.
    - Will register signal handlers for fatal handlers (clobbering old values).
    """
    # TODO: check for noop on both of the arguments!
    # Ensure the directory is suitable for writing to, or raise.
    log_dir = cls._check_or_create_new_destination(
      log_location_request.log_dir)
    pid = log_location_request.pid

    pid_specific_error_stream, shared_error_stream = cls._recapture_fatal_error_log_streams(
      log_dir, pid)

    # NB: mutate process-global state!
    cls._register_global_fatal_signal_handlers(pid_specific_error_stream)

    # NB: mutate the class variables!
    cls._log_dir = log_dir
    cls._pid = pid
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
  def exceptions_log_path(cls, log_location_request):
    if log_location_request.pid is None:
      intermediate_filename_component = ''
    else:
      intermediate_filename_component = '.{}'.format(log_location_request.pid)
    in_dir = log_location_request.log_dir or cls._log_dir
    return os.path.join(
      in_dir,
      'logs',
      'exceptions{}.log'.format(intermediate_filename_component))

  @classmethod
  def log_exception(cls, msg):
    try:
      fatal_error_log_entry = cls._format_exception_message(msg, cls._pid)
      # We care more about this log than the shared log, so write to it first.
      cls._pid_specific_error_fileobj.write(fatal_error_log_entry)
      cls._pid_specific_error_fileobj.flush()
      # TODO: we should probably guard this against concurrent modification by other pants
      # subprocesses somehow.
      cls._shared_error_fileobj.write(fatal_error_log_entry)
      cls._shared_error_fileobj.flush()
    except Exception as e:
      logger.error(
        'Problem logging original exception: {}. The original error message was:\n{}'
        .format(e, msg))

  @classmethod
  def _check_or_create_new_destination(cls, destination):
    try:
      safe_mkdir(destination)
    except Exception as e:
      raise cls.ExceptionSinkError(
        "The provided exception sink path at '{}' is not writable or could not be created: {}."
        .format(destination, str(e)),
        e)
    return destination

  @classmethod
  def _recapture_fatal_error_log_streams(cls, to_dir, for_pid):
    # NB: We do not close old file descriptors! This is bounded by the number of times any method is
    # called, which should be few and finite.
    # We recapture both log streams each time.
    assert(isinstance(for_pid, int))
    # NB: We truncate the pid-specific error log file.
    pid_specific_log_path = cls.exceptions_log_path(LogLocation(to_dir, for_pid))
    shared_log_path = cls.exceptions_log_path(LogLocation(to_dir))
    try:
      pid_specific_error_stream = safe_open(pid_specific_log_path, mode='w')
      shared_error_stream = safe_open(shared_log_path, mode='a')
    except Exception as e:
      raise cls.ExceptionSinkError(
        "Error opening fatal error log streams in {} for pid {}: {}"
        .format(to_dir, for_pid, str(e)))

    # TODO: determine whether any further validation of the streams (try writing to them here?) is
    # useful/necessary for faulthandler (it seems it just doesn't write to e.g. closed file
    # descriptors, so probably not).
    return (pid_specific_error_stream, shared_error_stream)

  @staticmethod
  def _register_global_fatal_signal_handlers(error_stream):
    # This is a purely side-effecting method.
    # TODO: is this check/disable step required?
    if faulthandler.is_enabled():
      faulthandler.disable()
    # Send a stacktrace to this file if interrupted by a fatal error.
    faulthandler.enable(file=error_stream, all_threads=True)

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

  @classmethod
  def _format_traceback(cls, tb, should_print_backtrace):
    if should_print_backtrace:
      traceback_string = ''.join(traceback.format_tb(tb))
    else:
      traceback_string = '(backtrace omitted)'
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
  def _log_unhandled_exception_and_exit(cls, exc_class=None, exc=None, tb=None, add_newline=False):
    """Default sys.excepthook implementation for unhandled exceptions."""
    exc_class = exc_class or sys.exc_info()[0]
    exc = exc or sys.exc_info()[1]
    tb = tb or sys.exc_info()[2]

    # Always output the unhandled exception details into a log file, including the traceback.
    exception_log_entry = cls._format_unhandled_exception_log(exc, tb, add_newline,
                                                              should_print_backtrace=True)
    cls.log_exception(exception_log_entry)

    # Generate an unhandled exception report fit to be printed to the terminal (respecting the
    # Exiter's _should_print_backtrace field).
    # TODO: the Exiter just prints to stderr -- is that always open? Should we manage that here too?
    stderr_printed_error = cls._format_unhandled_exception_log(
      exc, tb, add_newline,
      should_print_backtrace=cls._exiter.should_print_backtrace)

    # Exit with failure, printing a message to the terminal (or whatever the interactive stream is).
    cls._exiter.exit(result=cls.UNHANDLED_EXCEPTION_EXIT_CODE,
                     msg=stderr_printed_error,
                     out=cls._interactive_output_stream)


# Setup global state such as signal handlers and sys.excepthook with probably-safe values at module
# import time.
# Sets fatal signal handlers with reasonable defaults to catch errors early in startup.
ExceptionSink.reset_log_location(LogLocation(log_dir=os.getcwd(), pid=os.getpid()))
# Sets except hook.
ExceptionSink.reset_exiter(Exiter(print_backtraces=True))
# Sets a SIGUSR2 handler.
ExceptionSink.reset_interactive_output_stream(sys.stderr)
