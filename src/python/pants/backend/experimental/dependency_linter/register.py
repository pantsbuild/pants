# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.experimental.dependency_linter.rules import rules as linter_rules
from pants.backend.experimental.dependency_linter.target_types import DependencyRuleTarget


def target_types():
    return [DependencyRuleTarget]


def rules():
    return linter_rules()
