# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import os
import sys
import time
from collections import namedtuple
from logging import FileHandler, Formatter, StreamHandler

from future.moves.http import client

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
  client.HTTPConnection.debuglevel = 1
  requests_logger = logging.getLogger('requests.packages.urllib3')
  requests_logger.setLevel(TRACE)
  requests_logger.propagate = True


def _maybe_configure_extended_logging(logger):
  if logger.isEnabledFor(TRACE):
    _configure_requests_debug_logging()


def setup_logging_from_options(bootstrap_options):
  # N.B. quiet help says 'Squelches all console output apart from errors'.
  level = 'ERROR' if bootstrap_options.quiet else bootstrap_options.level.upper()
  return setup_logging(level, console_stream=sys.stderr, log_dir=bootstrap_options.logdir)


def setup_logging(level, console_stream=None, log_dir=None, scope=None, log_name=None):
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
    console_handler = StreamHandler(stream=console_stream)
    console_handler.setFormatter(Formatter(fmt='%(levelname)s] %(message)s'))
    console_handler.setLevel(level)
    logger.addHandler(console_handler)

  if log_dir:
    safe_mkdir(log_dir)
    log_filename = os.path.join(log_dir, log_name or 'pants.log')
    file_handler = FileHandler(log_filename)

    class GlogFormatter(Formatter):
      LEVEL_MAP = {
        logging.FATAL: 'F',
        logging.ERROR: 'E',
        logging.WARN: 'W',
        logging.INFO: 'I',
        logging.DEBUG: 'D',
        TRACE: 'T'
      }

      def format(self, record):
        datetime = time.strftime('%m%d %H:%M:%S', time.localtime(record.created))
        micros = int((record.created - int(record.created)) * 1e6)
        return '{levelchar}{datetime}.{micros:06d} {process} {filename}:{lineno}] {msg}'.format(
          levelchar=self.LEVEL_MAP[record.levelno],
          datetime=datetime,
          micros=micros,
          process=record.process,
          filename=record.filename,
          lineno=record.lineno,
          msg=record.getMessage()
        )

    file_handler.setFormatter(GlogFormatter())
    file_handler.setLevel(level)
    logger.addHandler(file_handler)

  logger.setLevel(level)

  # This routes warnings through our loggers instead of straight to raw stderr.
  logging.captureWarnings(True)

  _maybe_configure_extended_logging(logger)

  return LoggingSetupResult(log_filename, file_handler)
