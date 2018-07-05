# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import httplib
import logging
import os
import sys
import time
from collections import namedtuple
from logging import FileHandler, Formatter, StreamHandler

import six

from pants.util.dirutil import safe_mkdir


class LoggingSetupResult(namedtuple('LoggingSetupResult', ['log_filename', 'log_handler'])):
  """A structured result for logging setup."""


def _configure_requests_debug_logging():
  httplib.HTTPConnection.debuglevel = 1
  requests_logger = logging.getLogger('requests.packages.urllib3')
  requests_logger.setLevel(logging.DEBUG)
  requests_logger.propagate = True


def _maybe_configure_extended_logging(verbosity):
  """Sets up extended logging based on the verbosity level."""
  if not verbosity:
    return

  # Proxies the pants verbosity level forward to pex.
  os.environ['PEX_VERBOSE'] = six.text_type(verbosity)

  if verbosity >= 9:
    _configure_requests_debug_logging()


def setup_logging_from_options(bootstrap_options):
  # N.B. quiet help says 'Squelches all console output apart from errors'.
  level = 'ERROR' if bootstrap_options.quiet else bootstrap_options.level.upper()
  return setup_logging(
    level,
    console_stream=sys.stderr,
    log_dir=bootstrap_options.logdir,
    v=bootstrap_options.verbosity
  )


def setup_logging(level, console_stream=None, log_dir=None, scope=None, log_name=None, v=0):
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
  :param int v: The verbosity level for extended log configuration.
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
        logging.DEBUG: 'D'
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

  if v:
    _maybe_configure_extended_logging(v)

  return LoggingSetupResult(log_filename, file_handler)
