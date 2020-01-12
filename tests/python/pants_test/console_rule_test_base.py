# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.testutil.goal_rule_test_base import GoalRuleTestBase as ConsoleRuleTestBase  # noqa
from pants_test.deprecated_testinfra import deprecated_testinfra_module


deprecated_testinfra_module(instead="pants.testutil.goal_rule_test_base")
