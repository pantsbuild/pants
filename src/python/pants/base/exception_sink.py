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

from pants.base.exiter import Exiter
from pants.util.dirutil import safe_file_dump, safe_mkdir


logger = logging.getLogger(__name__)


class ExceptionSink(object):
  """A mutable singleton object representing where exceptions should be logged to."""

  # TODO: see the bottom of this file where we call set_destination() and friends in order to
  # properly setup global state.
  # TODO: ???
  _destination = None
  # We need an exiter in order to know what to do after we log a fatal exception.
  _exiter = None
  # Where to log stacktraces to in a SIGUSR2 handler.
  _trace_stream = None

  def __new__(cls, *args, **kwargs):
    raise TypeError('Instances of {} are not allowed to be constructed!'
                    .format(cls.__name__))

  class ExceptionSinkError(Exception): pass

  # TODO: ensure all set_* methods are idempotent!
  @classmethod
  def set_destination(cls, dir_path):
    cls._destination = cls._check_or_create_new_destination(dir_path)

  @classmethod
  def get_destination(cls):
    return cls._destination

  @classmethod
  def exceptions_log_path(cls, for_pid=None, in_dir=None):
    if not in_dir:
      in_dir = cls.get_destination()
    intermediate_filename_component = '.{}'.format(for_pid) if for_pid else ''
    return os.path.join(
      in_dir,
      'logs',
      'exceptions{}.log'.format(intermediate_filename_component))

  @classmethod
  def set_exiter(cls, exiter):
    assert(isinstance(exiter, Exiter))
    cls._exiter = exiter
    sys.excepthook = cls._log_unhandled_exception_and_exit

  @classmethod
  def set_trace_stream(cls, trace_stream):
    # TODO: validate trace_stream somehow!
    # TODO: do we need to keep a reference to this? I think not.
    cls._trace_stream = trace_stream

    # TODO: move /all/ signal handling into a SignalHandler class defined in this file which is not
    # a singleton and can be subclassed (like Exiter). Since signals are global, it is useful to
    # be able to look at all the signal handlers which are set in one place.
    if faulthandler.is_enabled():
      faulthandler.disable()
    faulthandler.enable(trace_stream)
    # This permits a non-fatal `kill -31 <pants pid>` for stacktrace retrieval.
    faulthandler.register(signal.SIGUSR2, trace_stream, chain=True)

  @classmethod
  def _check_or_create_new_destination(cls, destination):
    try:
      safe_mkdir(destination)
    except Exception as e:
      # NB: When this class sets up excepthooks, raising this should be safe, because we always
      # have a destination to log to (os.getcwd() if not otherwise set).
      raise cls.ExceptionSinkError(
        "The provided exception sink path at '{}' is not writable or could not be created: {}."
        .format(destination, str(e)),
        e)
    return destination

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
      message=msg,
    )

  @classmethod
  def log_exception(cls, msg):
    try:
      pid = os.getpid()
      fatal_error_log_entry = cls._format_exception_message(msg, pid)
      # We care more about this log than the shared log, so completely write to it first. This
      # avoids any errors with concurrent modification of the shared log affecting the per-pid log.
      safe_file_dump(cls.exceptions_log_path(for_pid=pid), fatal_error_log_entry, mode='w')
      # TODO: we should probably guard this against concurrent modification somehow.
      safe_file_dump(cls.exceptions_log_path(), fatal_error_log_entry, mode='a')
    except Exception as e:
      # TODO: If there is an error in writing to the exceptions log, we may want to consider trying
      # to write to another location (e.g. the cwd, if that is not already the destination).
      logger.error('Problem logging original exception: {}'.format(e))

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
      maybe_newline=maybe_newline,
    )

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

    cls._exiter.exit(result=1, msg=stderr_printed_error, out=cls._trace_stream)


# NB: setup global state such as signal handlers and sys.excepthook with probably-safe values.
# Get the current directory at class initialization time -- this is probably (definitely?) a
# writable directory. Using this directory as a fallback increases the chances that if an
# exception occurs early in initialization that we still record it somewhere.
ExceptionSink.set_destination(os.getcwd())
ExceptionSink.set_exiter(Exiter(print_backtraces=True))
ExceptionSink.set_trace_stream(sys.stderr)
