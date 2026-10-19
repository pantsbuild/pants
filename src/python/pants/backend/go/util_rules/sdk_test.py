# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.go.util_rules import sdk
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.engine.process import Process
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            QueryRule(Process, [GoSdkProcess]),
        ],
    )
    rule_runner.set_options([], env_inherit={"PATH"})
    return rule_runner


def test_gotoolchain_local_is_set(rule_runner: RuleRunner) -> None:
    """GOTOOLCHAIN=local must be present in every GoSdkProcess environment."""
    process = rule_runner.request(
        Process,
        [GoSdkProcess(["version"], description="test: go version")],
    )
    assert process.env.get("GOTOOLCHAIN") == "local"


def test_gotoolchain_local_cannot_be_overridden(rule_runner: RuleRunner) -> None:
    """GOTOOLCHAIN=local must survive even when the caller passes a different value via
    GoSdkProcess(env=...).  The pin is placed after **request.env in the dict literal so
    caller-supplied values are silently overwritten."""
    process = rule_runner.request(
        Process,
        [
            GoSdkProcess(
                ["version"],
                description="test: override attempt",
                env=FrozenDict({"GOTOOLCHAIN": "auto"}),
            )
        ],
    )
    assert process.env.get("GOTOOLCHAIN") == "local"


def test_modcacherw_set_when_downloads_allowed(rule_runner: RuleRunner) -> None:
    """A download-enabled process must pass `-modcacherw` so Go leaves the extracted module
    cache owner-writable and Pants can tear the sandbox down instead of leaking it."""
    process = rule_runner.request(
        Process,
        [GoSdkProcess(["mod", "download"], description="test: download", allow_downloads=True)],
    )
    assert "-modcacherw" in process.env.get("GOFLAGS", "").split()


def test_modcacherw_absent_when_downloads_disabled(rule_runner: RuleRunner) -> None:
    """A process that does not download must not add `-modcacherw`; it never extracts modules,
    so there is nothing to leave writable, and GOPROXY is pinned off instead."""
    process = rule_runner.request(
        Process,
        [GoSdkProcess(["version"], description="test: no download")],
    )
    assert "-modcacherw" not in process.env.get("GOFLAGS", "").split()
    assert process.env.get("GOPROXY") == "off"


def test_modcacherw_appends_to_existing_goflags(rule_runner: RuleRunner) -> None:
    """`-modcacherw` must extend any caller-supplied GOFLAGS rather than replace it."""
    process = rule_runner.request(
        Process,
        [
            GoSdkProcess(
                ["mod", "download"],
                description="test: preserve GOFLAGS",
                env=FrozenDict({"GOFLAGS": "-mod=readonly"}),
                allow_downloads=True,
            )
        ],
    )
    goflags = process.env.get("GOFLAGS", "").split()
    assert "-mod=readonly" in goflags
    assert "-modcacherw" in goflags


def test_modcacherw_appends_to_subsystem_goflags() -> None:
    """`-modcacherw` must extend a GOFLAGS passed through `[golang].subprocess_env_vars` rather
    than replace it.  The flag is appended after the subsystem env vars are merged into the
    process env, so it must compose with them, not clobber them."""
    rule_runner = RuleRunner(
        rules=[
            *sdk.rules(),
            QueryRule(Process, [GoSdkProcess]),
        ],
    )
    rule_runner.set_options(
        ["--golang-subprocess-env-vars=['PATH', 'GOFLAGS']"],
        env={"GOFLAGS": "-mod=readonly"},
        env_inherit={"PATH"},
    )
    process = rule_runner.request(
        Process,
        [
            GoSdkProcess(
                ["mod", "download"],
                description="test: subsystem GOFLAGS",
                allow_downloads=True,
            )
        ],
    )
    goflags = process.env.get("GOFLAGS", "").split()
    assert "-mod=readonly" in goflags
    assert "-modcacherw" in goflags
