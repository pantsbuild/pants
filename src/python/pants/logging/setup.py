# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import time
from logging import Formatter, StreamHandler
from logging.handlers import RotatingFileHandler

from pants.util.dirutil import safe_mkdir


def setup_logging(level, console_stream=None, log_dir=None, scope=None):
  """Configures logging for a given scope, by default the global scope.

  :param str level: The logging level to enable, must be one of the level names listed here:
                    https://docs.python.org/2/library/logging.html#levels
  :param str console_stream: The stream to use for default (console) logging.  Will be sys.stderr
                             if unspecified.
  :param str log_dir: An optional directory to emit logs files in.  If unspecified, no disk logging
                      will occur.  If supplied, the directory will be created if it does not already
                      exist and all logs will be tee'd to a rolling set of log files in that
                      directory.
  :param str scope: A logging scope to configure.  The scopes are hierarchichal logger names, with
                    The '.' separator providing the scope hierarchy.  By default the root logger is
                    configured.
  :returns: The full path to the main log file if file logging is configured or else `None`.
  :rtype: str
  """

  # TODO(John Sirois): Consider moving to straight python logging.  The divide between the
  # context/work-unit logging and standard python logging doesn't buy us anything.

  # TODO(John Sirois): Support logging.config.fileConfig so a site can setup fine-grained
  # logging control and we don't need to be the middleman plumbing an option for each python
  # standard logging knob.

  logger = logging.getLogger(scope)
  for handler in logger.handlers:
    logger.removeHandler(handler)

  log_file = None
  console_handler = StreamHandler(stream=console_stream)
  console_handler.setFormatter(Formatter(fmt='%(levelname)s] %(message)s'))
  console_handler.setLevel(level)
  logger.addHandler(console_handler)

  if log_dir:
    safe_mkdir(log_dir)
    log_file = os.path.join(log_dir, 'pants.log')
    file_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=4)

    class GlogFormatter(Formatter):
      LEVEL_MAP = {
          logging.FATAL: 'F',
          logging.ERROR: 'E',
          logging.WARN: 'W',
          logging.INFO: 'I',
          logging.DEBUG: 'D'}

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
            msg=record.getMessage())

    file_handler.setFormatter(GlogFormatter())
    file_handler.setLevel(level)
    logger.addHandler(file_handler)

  logger.setLevel(level)
  return log_file
