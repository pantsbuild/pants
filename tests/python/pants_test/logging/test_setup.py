# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import unittest
import uuid
from contextlib import closing, contextmanager

import six

from pants.logging.setup import setup_logging
from pants.util.contextutil import temporary_dir


class SetupTest(unittest.TestCase):
  @contextmanager
  def log_dir(self, file_logging):
    if file_logging:
      with temporary_dir() as log_dir:
        yield log_dir
    else:
      yield None

  @contextmanager
  def logger(self, level, file_logging=False):
    logger = logging.getLogger(str(uuid.uuid4()))
    with closing(six.StringIO()) as stream:
      with self.log_dir(file_logging) as log_dir:
        log_file = setup_logging(level, console_stream=stream, log_dir=log_dir, scope=logger.name)
        yield logger, stream, log_file

  def assertWarnInfoOutput(self, lines):
    """Check to see that only warn and info output appears in the stream.

    The first line may start with WARN] or WARNING] depending on whether 'WARN'
    has been registered as a global log level.  See options_bootstrapper.py.
    """
    self.assertEqual(2, len(lines))
    self.assertRegexpMatches(lines[0], '^WARN\w*] warn')
    self.assertEqual('INFO] info', lines[1])

  def test_standard_logging(self):
    with self.logger('INFO') as (logger, stream, _):
      logger.warn('warn')
      logger.info('info')
      logger.debug('debug')

      stream.flush()
      stream.seek(0)
      self.assertWarnInfoOutput(stream.read().splitlines())

  def test_file_logging(self):
    with self.logger('INFO', file_logging=True) as (logger, stream, log_file):
      logger.warn('warn')
      logger.info('info')
      logger.debug('debug')

      stream.flush()
      stream.seek(0)
      self.assertWarnInfoOutput(stream.read().splitlines())

      with open(log_file) as fp:
        loglines = fp.read().splitlines()
        self.assertEqual(2, len(loglines))
        glog_format = r'\d{4} \d{2}:\d{2}:\d{2}.\d{6} \d+ \w+\.py:\d+] '
        self.assertRegexpMatches(loglines[0], r'^W{}warn$'.format(glog_format))
        self.assertRegexpMatches(loglines[1], r'^I{}info$'.format(glog_format))
