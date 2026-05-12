# Copyright 2026 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import pytest

from pants.backend.observability.opentelemetry import register
from pants.backend.observability.opentelemetry.register import (
    TelemetryWorkunitsCallbackFactoryRequest,
)
from pants.backend.observability.opentelemetry.subsystem import TracingExporterId
from pants.backend.observability.opentelemetry.workunit_handler import TelemetryWorkunitsCallback
from pants.engine.rules import QueryRule
from pants.engine.streaming_workunit_handler import WorkunitsCallbackFactory
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=(
            *register.rules(),
            QueryRule(WorkunitsCallbackFactory, (TelemetryWorkunitsCallbackFactoryRequest,)),
        ),
    )
    rule_runner.set_options(
        [
            "--opentelemetry-enabled",
            f"--opentelemetry-exporter={TracingExporterId.JSON_FILE.value}",
        ]
    )
    return rule_runner


def test_workunit_callback_factory_setup(rule_runner: RuleRunner) -> None:
    callback_factory = rule_runner.request(
        WorkunitsCallbackFactory, [TelemetryWorkunitsCallbackFactoryRequest()]
    )
    callback = callback_factory.callback_factory()
    assert callback is not None
    assert isinstance(callback, TelemetryWorkunitsCallback)
