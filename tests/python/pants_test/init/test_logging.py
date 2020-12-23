# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from pathlib import Path

from pants.engine.internals.native import Native
from pants.init.logging import setup_logging_to_file
from pants.util.contextutil import temporary_dir
from pants.util.logging import LogLevel


def test_file_logging() -> None:
    native = Native()
    native.init_rust_logging(
        level=LogLevel.INFO.level,  # Tests assume a log level of INFO
        log_show_rust_3rdparty=False,
        use_color=False,
        show_target=False,
        log_levels_by_target={},
        message_regex_filters=(),
    )
    logger = logging.getLogger("my_file_logger")
    with temporary_dir() as tmpdir:
        setup_logging_to_file(LogLevel.INFO, log_dir=tmpdir)
        log_file = Path(tmpdir, "pants.log")

        cat = "🐈"
        logger.warning("this is a warning")
        logger.info("this is some info")
        logger.debug("this is some debug info")
        logger.info(f"unicode: {cat}")

        loglines = log_file.read_text().splitlines()
        print(loglines)
        assert len(loglines) == 3
        assert "[WARN] this is a warning" in loglines[0]
        assert "[INFO] this is some info" in loglines[1]
        assert f"[INFO] unicode: {cat}" in loglines[2]


def test_log_filtering_by_rule() -> None:
    native = Native()
    native.init_rust_logging(
        level=LogLevel.INFO.level,
        log_show_rust_3rdparty=False,
        use_color=False,
        show_target=True,
        log_levels_by_target={
            "debug_target": LogLevel.DEBUG,
        },
        message_regex_filters=(),
    )
    with temporary_dir() as tmpdir:
        setup_logging_to_file(LogLevel.INFO, log_dir=tmpdir)
        log_file = Path(tmpdir, "pants.log")

        native.write_log(msg="log msg one", level=LogLevel.INFO.level, target="some.target")
        native.write_log(msg="log msg two", level=LogLevel.DEBUG.level, target="some.other.target")
        native.write_log(msg="log msg three", level=LogLevel.DEBUG.level, target="debug_target")

        loglines = log_file.read_text().splitlines()

        assert "[INFO] (some.target) log msg one" in loglines[0]
        assert "[DEBUG] (debug_target) log msg three" in loglines[1]
        assert len(loglines) == 2
