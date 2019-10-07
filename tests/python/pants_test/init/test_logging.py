# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from contextlib import contextmanager
from pathlib import Path

from pants.init.logging import get_numeric_level, setup_logging
from pants.util.contextutil import temporary_dir
from pants_test.test_base import TestBase


class LoggingTest(TestBase):
    def post_scheduler_init(self):
        self.native = self.scheduler._scheduler._native
        # Initialize it with the least verbose level.
        # Individual loggers will increase verbosity as needed.
        self.native.init_rust_logging(get_numeric_level("ERROR"), False)

    @contextmanager
    def logger(self, level):
        native = self.scheduler._scheduler._native
        logger = logging.getLogger("my_file_logger")
        with temporary_dir() as log_dir:
            logging_setup_result = setup_logging(
                level, log_dir=log_dir, scope=logger.name, native=native
            )
            yield logger, logging_setup_result

    def test_utf8_logging(self):
        with self.logger("INFO") as (file_logger, logging_setup_result):
            cat = "🐈"
            file_logger.info(cat)
            logging_setup_result.log_handler.flush()
            self.assertIn(cat, Path(logging_setup_result.log_filename).read_text())

    def test_file_logging(self):
        with self.logger("INFO") as (file_logger, logging_setup_result):
            file_logger.warning("this is a warning")
            file_logger.info("this is some info")
            file_logger.debug("this is some debug info")
            logging_setup_result.log_handler.flush()

            loglines = Path(logging_setup_result.log_filename).read_text().splitlines()
            self.assertEqual(2, len(loglines))
            self.assertIn("[WARN] this is a warning", loglines[0])
            self.assertIn("[INFO] this is some info", loglines[1])
