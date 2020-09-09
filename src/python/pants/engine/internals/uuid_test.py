# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.engine.internals.uuid import UUID, UUIDRequest
from pants.engine.internals.uuid import rules as uuid_rules
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(rules=[*uuid_rules(), QueryRule(UUID, (UUIDRequest,))])


def test_distinct_uuids(rule_runner: RuleRunner) -> None:
    uuid1 = rule_runner.request_product(UUID, [UUIDRequest()])
    uuid2 = rule_runner.request_product(UUID, [UUIDRequest()])
    assert uuid1 != uuid2


def test_identical_uuids(rule_runner: RuleRunner) -> None:
    uuid1 = rule_runner.request_product(UUID, [UUIDRequest(randomizer=0.0)])
    uuid2 = rule_runner.request_product(UUID, [UUIDRequest(randomizer=0.0)])
    assert uuid1 == uuid2
