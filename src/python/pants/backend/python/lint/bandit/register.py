# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.lint.bandit import rules as bandit_rules


def rules():
    return bandit_rules.rules()
