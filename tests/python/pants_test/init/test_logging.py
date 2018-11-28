# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging
import uuid
from builtins import open, str
from contextlib import contextmanager

from pants.init.logging import get_numeric_level, setup_logging
from pants.util.contextutil import temporary_dir
from pants_test.test_base import TestBase


class LoggingTest(TestBase):

  def post_scheduler_init(self):
    self.native = self.scheduler._scheduler._native
    # Initialize it with the least verbose level.
    # Individual loggers will increase verbosity as needed.
    self.native.init_rust_logging(get_numeric_level("ERROR"))

  @contextmanager
  def logger(self, level):
    native = self.scheduler._scheduler._native
    logger = logging.getLogger(str(uuid.uuid4()))
    with temporary_dir() as log_dir:
      log_file = setup_logging(level, log_dir=log_dir, scope=logger.name, native=native)
      yield logger, log_file.log_filename

  def test_utf8_logging(self):
    with self.logger('INFO') as (file_logger, log_file):
      cat = "🐈"
      file_logger.info(cat)
      with open(log_file, "r") as fp:
        contents = fp.read()
        self.assertTrue(cat in contents)

  def test_file_logging(self):
    with self.logger('INFO') as (file_logger, log_file):
      file_logger.warn('warn')
      file_logger.info('info')
      file_logger.debug('debug')

      with open(log_file, 'r') as fp:
        loglines = fp.read().splitlines()
        self.assertEqual(2, len(loglines))
        self.assertTrue("[WARN] warn" in loglines[0])
        self.assertTrue("[INFO] info" in loglines[1])
