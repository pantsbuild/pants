# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from uuid import UUID

import pytest

from pants.engine.internals.uuid import UUIDRequest, UUIDScope
from pants.engine.internals.uuid import rules as uuid_rules
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(rules=[*uuid_rules(), QueryRule(UUID, (UUIDRequest,))])


def test_distinct_uuids_default_scope(rule_runner: RuleRunner) -> None:
    uuid1 = rule_runner.request(UUID, [UUIDRequest()])
    uuid2 = rule_runner.request(UUID, [UUIDRequest()])
    assert uuid1 != uuid2


def test_distinct_uuids_different_scopes(rule_runner: RuleRunner) -> None:
    uuid1 = rule_runner.request(UUID, [UUIDRequest(scope="this")])
    uuid2 = rule_runner.request(UUID, [UUIDRequest(scope="that")])
    assert uuid1 != uuid2


def test_identical_uuids_same_scope(rule_runner: RuleRunner) -> None:
    uuid1 = rule_runner.request(UUID, [UUIDRequest(scope="this")])
    uuid2 = rule_runner.request(UUID, [UUIDRequest(scope="this")])
    assert uuid1 == uuid2


def test_distinct_uuids_call_scope(rule_runner: RuleRunner) -> None:
    uuid1 = rule_runner.request(UUID, [UUIDRequest()])
    uuid2 = rule_runner.request(UUID, [UUIDRequest(scope="bob")])
    uuid3 = rule_runner.request(UUID, [UUIDRequest.scoped(UUIDScope.PER_CALL)])
    uuid4 = rule_runner.request(UUID, [UUIDRequest.scoped(UUIDScope.PER_CALL)])
    assert uuid1 != uuid2 != uuid3 != uuid4


def test_identical_uuids_session_scope(rule_runner: RuleRunner) -> None:
    uuid1 = rule_runner.request(UUID, [UUIDRequest.scoped(UUIDScope.PER_SESSION)])
    uuid2 = rule_runner.request(UUID, [UUIDRequest.scoped(UUIDScope.PER_SESSION)])
    assert uuid1 == uuid2
