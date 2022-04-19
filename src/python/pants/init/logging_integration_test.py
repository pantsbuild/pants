# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.pants_integration_test import PantsResult, run_pants, setup_tmpdir

PLUGIN = """
import logging

from pants.engine.goal import GoalSubsystem, Goal
from pants.engine.rules import collect_rules, goal_rule

class LogSubsystem(GoalSubsystem):
    name = "logger"
    help = "foo"


class LogGoal(Goal):
    subsystem_cls = LogSubsystem


@goal_rule
def write_logs() -> LogGoal:
    for logger_name in ("globalLevel", "infoOverride", "debugOverride"):
        logger = logging.getLogger(f"plugins.logger.{{logger_name}}")
        logger.debug("debug log")
        logger.info("info log")
        logger.warning("warn log")
    return LogGoal(exit_code=0)

def rules():
    return collect_rules()
"""

REGISTER = """
from plugins import logger

def rules():
    return logger.rules()
"""

GLOBAL_LEVEL = "globalLevel"
INFO_OVERRIDE = "infoOverride"
DEBUG_OVERRIDE = "debugOverride"


def run_pants_with_opts(*extra_options: str) -> PantsResult:
    with setup_tmpdir({"plugins/logger.py": PLUGIN, "plugins/register.py": REGISTER}) as tmpdir:
        return run_pants(
            [
                f"--pythonpath={tmpdir}",
                "--backend-packages=plugins",
                "--no-dynamic-ui",
                "--show-log-target",
                "--level=warn",
                *extra_options,
                (
                    "--log-levels-by-target={"
                    "'plugins.logger.infoOverride': 'info', "
                    "'plugins.logger.debugOverride': 'debug', "
                    "'workunit_store': 'debug'}"
                ),
                "logger",
            ]
        )


def test_log_by_level() -> None:
    """Check that overriding log levels works for logs both coming from Rust and from Python.

    This also checks that we correctly log `Starting` and `Completed` messages when the dynamic UI
    is disabled.
    """
    result = run_pants_with_opts()

    for logger in (GLOBAL_LEVEL, INFO_OVERRIDE, DEBUG_OVERRIDE):
        assert f"[WARN] (plugins.logger.{logger}) warn log" in result.stderr

    for logger in (INFO_OVERRIDE, DEBUG_OVERRIDE):
        assert f"[INFO] (plugins.logger.{logger}) info log" in result.stderr
    assert "[INFO] (plugins.logger.globalLevel) info log" not in result.stderr

    assert "[DEBUG] (plugins.logger.debugOverride) debug log" in result.stderr
    for logger in (GLOBAL_LEVEL, INFO_OVERRIDE):
        assert f"[DEBUG] (plugins.logger.{logger} debug log" not in result.stderr

    # Check that overriding levels for Rust code works, and also that we log Starting and Completed
    # properly.
    assert "[DEBUG] (workunit_store) Starting: `logger` goal" in result.stderr
    assert "[DEBUG] (workunit_store) Completed: `logger` goal" in result.stderr


def test_console_level_filter() -> None:
    result = run_pants_with_opts("--console-level-filter=warn")

    for logger in (GLOBAL_LEVEL, INFO_OVERRIDE, DEBUG_OVERRIDE):
        assert f"[WARN] (plugins.logger.{logger}) warn log" in result.stderr
        assert f"[INFO] (plugins.logger.{logger}) info log" not in result.stderr
        assert f"[DEBUG] (plugins.logger.{logger} debug log" not in result.stderr

    assert "workunit_store" not in result.stderr
