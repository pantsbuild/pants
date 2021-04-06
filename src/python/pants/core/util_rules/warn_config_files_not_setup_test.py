# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.core.util_rules import warn_config_files_not_setup
from pants.core.util_rules.warn_config_files_not_setup import (
    WarnConfigFilesNotSetup,
    WarnConfigFilesNotSetupResult,
)
from pants.testutil.rule_runner import QueryRule, RuleRunner


def test_warn_if_config_file_not_setup(caplog) -> None:
    rule_runner = RuleRunner(
        rules=[
            *warn_config_files_not_setup.rules(),
            QueryRule(WarnConfigFilesNotSetupResult, [WarnConfigFilesNotSetup]),
        ],
    )
    rule_runner.write_files({"c1": "", "c2": "", "c3": "foo", "c4": "bar"})

    def warn(existence: list[str], content: dict[str, bytes]) -> None:
        caplog.clear()
        rule_runner.request(
            WarnConfigFilesNotSetupResult,
            [
                WarnConfigFilesNotSetup(
                    check_existence=existence,
                    check_content=content,
                    option_name="[subsystem].config",
                )
            ],
        )

    warn(["c1", "fake"], {"c3": b"foo", "c4": b"bad"})
    assert len(caplog.records) == 1
    assert (
        "The option `[subsystem].config` is not configured, but Pants detected relevant config "
        "files at ['c1', 'c3']."
    ) in caplog.text

    warn(["c1"], {})
    assert len(caplog.records) == 1
    assert (
        "The option `[subsystem].config` is not configured, but Pants detected a relevant config "
        "file at c1."
    ) in caplog.text

    warn([], {})
    assert not caplog.records

    warn(["fake"], {"c4": b"bad"})
    assert not caplog.records
