# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import copy
import http.client
import logging
import os
import sys
from collections import namedtuple
from contextlib import contextmanager
from logging import StreamHandler

from pants.base.exception_sink import ExceptionSink
from pants.engine.native import Native
from pants.util.dirutil import safe_mkdir


# A custom log level for pants trace logging.
TRACE = 5

# Although logging supports the WARN level, its not documented and could conceivably be yanked.
# Since pants has supported 'warn' since inception, leave the 'warn' choice as-is but explicitly
# setup a 'WARN' logging level name that maps to 'WARNING'.
logging.addLevelName(logging.WARNING, 'WARN')
logging.addLevelName(TRACE, 'TRACE')


class LoggingSetupResult(namedtuple('LoggingSetupResult', ['log_filename', 'log_handler'])):
  """A structured result for logging setup."""


def _configure_requests_debug_logging():
  http.client.HTTPConnection.debuglevel = 1
  requests_logger = logging.getLogger('requests.packages.urllib3')
  requests_logger.setLevel(TRACE)
  requests_logger.propagate = True


def _maybe_configure_extended_logging(logger):
  if logger.isEnabledFor(TRACE):
    _configure_requests_debug_logging()


def init_rust_logger(level, log_show_rust_3rdparty):
  native = Native()
  levelno = get_numeric_level(level)
  native.init_rust_logging(levelno, log_show_rust_3rdparty)


def setup_logging_to_stderr(python_logger, level):
  """
  We setup logging as loose as possible from the Python side,
  and let Rust do the filtering.
  """
  native = Native()
  levelno = get_numeric_level(level)
  handler = create_native_stderr_log_handler(levelno, native, stream=sys.stderr)
  python_logger.addHandler(handler)
  # Let the rust side filter levels; try to have the python side send everything to the rust logger.
  python_logger.setLevel("TRACE")


def setup_logging_from_options(bootstrap_options):
  # N.B. quiet help says 'Squelches all console output apart from errors'.
  level = 'ERROR' if bootstrap_options.quiet else bootstrap_options.level.upper()
  native = Native()
  return setup_logging(level, console_stream=sys.stderr, log_dir=bootstrap_options.logdir, native=native)


class NativeHandler(StreamHandler):

  def __init__(self, level, native=None, stream=None, native_filename=None):
    super().__init__(stream)
    self.native = native
    self.native_filename = native_filename
    self.setLevel(level)

  def emit(self, record):
    self.native.write_log(self.format(record), record.levelno, f"{record.name}:pid={os.getpid()}")

  def flush(self):
    self.native.flush_log()

  def __repr__(self):
    return (
      f"NativeHandler(id={id(self)}, level={self.level}, filename={self.native_filename}, "
      f"stream={self.stream})"
    )


def create_native_pantsd_file_log_handler(level, native, native_filename):
  fd = native.setup_pantsd_logger(native_filename, get_numeric_level(level))
  ExceptionSink.reset_interactive_output_stream(os.fdopen(os.dup(fd), 'a'))
  return NativeHandler(level, native, native_filename=native_filename)


def create_native_stderr_log_handler(level, native, stream=None):
  try:
    native.setup_stderr_logger(get_numeric_level(level))
  except Exception as e:
    print(f"Error setting up pantsd logger: {e!r}", file=sys.stderr)
    raise e

  return NativeHandler(level, native, stream)


# TODO This function relies on logging._checkLevel, which is private.
# There is currently no good way to convert string levels to numeric values,
# but if there is ever one, it may be worth changing this.
def get_numeric_level(level):
  return logging._checkLevel(level)


@contextmanager
def encapsulated_global_logger():
  """Record all the handlers of the current global logger, yield, and reset that logger.
  This is useful in the case where we want to easily restore state after calling setup_logging.
  For instance, when DaemonPantsRunner creates an instance of LocalPantsRunner it sets up specific
  nailgunned logging, which we want to undo once the LocalPantsRunner has finished runnnig.
  """
  global_logger = logging.getLogger()
  old_handlers = copy.copy(global_logger.handlers)
  try:
    yield
  finally:
    new_handlers = global_logger.handlers
    for handler in new_handlers:
      global_logger.removeHandler(handler)
    for handler in old_handlers:
      global_logger.addHandler(handler)


def setup_logging(level, console_stream=None, log_dir=None, scope=None, log_name=None, native=None):
  """Configures logging for a given scope, by default the global scope.

  :param str level: The logging level to enable, must be one of the level names listed here:
                    https://docs.python.org/2/library/logging.html#levels
  :param file console_stream: The stream to use for default (console) logging. If None (default),
                              this will disable console logging.
  :param str log_dir: An optional directory to emit logs files in.  If unspecified, no disk logging
                      will occur.  If supplied, the directory will be created if it does not already
                      exist and all logs will be tee'd to a rolling set of log files in that
                      directory.
  :param str scope: A logging scope to configure.  The scopes are hierarchichal logger names, with
                    The '.' separator providing the scope hierarchy.  By default the root logger is
                    configured.
  :param str log_name: The base name of the log file (defaults to 'pants.log').
  :param Native native: An instance of the Native FFI lib, to register rust logging.
  :returns: The full path to the main log file if file logging is configured or else `None`.
  :rtype: str
  """

  # TODO(John Sirois): Consider moving to straight python logging.  The divide between the
  # context/work-unit logging and standard python logging doesn't buy us anything.

  # TODO(John Sirois): Support logging.config.fileConfig so a site can setup fine-grained
  # logging control and we don't need to be the middleman plumbing an option for each python
  # standard logging knob.

  log_filename = None
  file_handler = None

  # A custom log handler for sub-debug trace logging.
  def trace(self, message, *args, **kwargs):
    if self.isEnabledFor(TRACE):
      self._log(TRACE, message, args, **kwargs)

  logging.Logger.trace = trace

  logger = logging.getLogger(scope)
  for handler in logger.handlers:
    logger.removeHandler(handler)


  if console_stream:
    native_handler = create_native_stderr_log_handler(level, native, stream=console_stream)
    logger.addHandler(native_handler)

  if log_dir:
    safe_mkdir(log_dir)
    log_filename = os.path.join(log_dir, log_name or 'pants.log')

    native_handler = create_native_pantsd_file_log_handler(level, native, log_filename)
    file_handler = native_handler
    logger.addHandler(native_handler)


  logger.setLevel(level)

  # This routes warnings through our loggers instead of straight to raw stderr.
  logging.captureWarnings(True)

  _maybe_configure_extended_logging(logger)

  return LoggingSetupResult(log_filename, file_handler)
