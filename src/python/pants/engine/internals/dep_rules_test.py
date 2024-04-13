# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging

import pytest

from pants.engine.internals.dep_rules import DependencyRuleAction, DependencyRuleActionDeniedError
from pants.testutil.pytest_util import assert_logged


def test_dependency_rule_action(caplog) -> None:
    violation_msg = "Dependency rule violation for test"

    DependencyRuleAction("allow").execute(description_of_origin="test")
    assert_logged(caplog, expect_logged=None)
    caplog.clear()

    DependencyRuleAction("warn").execute(description_of_origin="test")
    assert_logged(caplog, expect_logged=[(logging.WARNING, violation_msg)])
    caplog.clear()

    with pytest.raises(DependencyRuleActionDeniedError, match=violation_msg):
        DependencyRuleAction("deny").execute(description_of_origin="test")
    assert_logged(caplog, expect_logged=None)
