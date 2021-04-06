# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.core.util_rules import config_files
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.engine.internals.scheduler import ExecutionError
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *config_files.rules(),
            QueryRule(ConfigFiles, [ConfigFilesRequest]),
        ],
    )


def test_resolve_if_specified(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"c1": "", "c2": ""})

    def resolve(specified: list[str]) -> ConfigFiles:
        return rule_runner.request(
            ConfigFiles, [ConfigFilesRequest(specified=specified, option_name="[subsystem].config")]
        )

    assert resolve(["c1", "c2"]).snapshot.files == ("c1", "c2")
    assert resolve(["c1"]).snapshot.files == ("c1",)
    with pytest.raises(ExecutionError) as exc:
        resolve(["fake"])
    assert "fake" in str(exc.value)


def test_warn_if_not_specified(rule_runner: RuleRunner, caplog) -> None:
    rule_runner.write_files({"c1": "", "c2": "", "c3": "foo", "c4": "bar"})

    def warn(existence: list[str], content: dict[str, bytes]) -> None:
        caplog.clear()
        rule_runner.request(
            ConfigFiles,
            [
                ConfigFilesRequest(
                    specified=None,
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
