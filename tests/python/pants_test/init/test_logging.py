# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from pathlib import Path

from pants.engine.internals import native_engine
from pants.init.logging import initialize_stdio
from pants.testutil.option_util import create_options_bootstrapper
from pants.util.contextutil import temporary_dir
from pants.util.logging import LogLevel


def test_file_logging() -> None:
    with temporary_dir() as tmpdir:
        ob = create_options_bootstrapper([f"--pants-workdir={tmpdir}"])

        # Do not set up a stdio destination, meaning that all messages will go to the log.
        global_bootstrap_options = ob.bootstrap_options.for_global_scope()
        with initialize_stdio(global_bootstrap_options):
            logger = logging.getLogger(None)

            cat = "🐈"
            logger.warning("this is a warning")
            logger.info("this is some info")
            logger.debug("this is some debug info")
            logger.info(f"unicode: {cat}")

            loglines = (
                Path(global_bootstrap_options.pants_workdir, "pants.log").read_text().splitlines()
            )
            print(loglines)
            assert len(loglines) == 3
            assert "[WARN] this is a warning" in loglines[0]
            assert "[INFO] this is some info" in loglines[1]
            assert f"[INFO] unicode: {cat}" in loglines[2]


def test_log_filtering_by_rule() -> None:
    with temporary_dir() as tmpdir:
        ob = create_options_bootstrapper(
            [f"--pants-workdir={tmpdir}", '--log-levels-by-target={"debug_target": "debug"}']
        )

        # Do not set up a stdio destination, meaning that all messages will go to the log.
        global_bootstrap_options = ob.bootstrap_options.for_global_scope()
        with initialize_stdio(global_bootstrap_options):
            native_engine.write_log(
                msg="log msg one", level=LogLevel.INFO.level, target="some.target"
            )
            native_engine.write_log(
                msg="log msg two", level=LogLevel.DEBUG.level, target="some.other.target"
            )
            native_engine.write_log(
                msg="log msg three", level=LogLevel.DEBUG.level, target="debug_target"
            )

            loglines = (
                Path(global_bootstrap_options.pants_workdir, "pants.log").read_text().splitlines()
            )

            assert "[INFO] log msg one" in loglines[0]
            assert "[DEBUG] log msg three" in loglines[1]
            assert len(loglines) == 2
