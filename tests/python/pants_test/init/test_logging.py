# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from contextlib import contextmanager
from logging import Logger
from pathlib import Path
from typing import Iterator, Tuple

from pants.init.logging import NativeHandler, setup_logging_to_file
from pants.testutil.engine.util import init_native
from pants.testutil.test_base import TestBase
from pants.util.contextutil import temporary_dir
from pants.util.logging import LogLevel


class LoggingTest(TestBase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        # NB: We must set this up at the class level, rather than per-test level, because
        # `init_rust_logging` must never be called more than once. The Rust logger is global and static,
        # and initializing it twice in the same test class results in a SIGABRT.
        init_native().init_rust_logging(
            # We set the level to the least verbose possible, as individual tests will increase the
            # verbosity as necessary.
            level=LogLevel.ERROR.level,
            log_show_rust_3rdparty=False,
        )

    @contextmanager
    def logger(self, log_level: LogLevel) -> Iterator[Tuple[Logger, NativeHandler, Path]]:
        native = self.scheduler._scheduler._native
        # TODO(gregorys) - if this line isn't here this test fails with no stdout. Figure out why.
        print(f"Native: {native}")
        logger = logging.getLogger("my_file_logger")
        with temporary_dir() as tmpdir:
            handler = setup_logging_to_file(log_level, log_dir=tmpdir)
            log_file = Path(tmpdir, "pants.log")
            yield logger, handler, log_file

    def test_utf8_logging(self) -> None:
        with self.logger(LogLevel.INFO) as (file_logger, log_handler, log_file):
            cat = "🐈"
            file_logger.info(cat)
            log_handler.flush()
            self.assertIn(cat, log_file.read_text())

    def test_file_logging(self) -> None:
        with self.logger(LogLevel.INFO) as (file_logger, log_handler, log_file):
            file_logger.warning("this is a warning")
            file_logger.info("this is some info")
            file_logger.debug("this is some debug info")
            log_handler.flush()

            loglines = log_file.read_text().splitlines()
            self.assertEqual(2, len(loglines))
            self.assertIn("[WARN] this is a warning", loglines[0])
            self.assertIn("[INFO] this is some info", loglines[1])
