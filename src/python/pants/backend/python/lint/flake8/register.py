# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.lint import python_lint_target
from pants.backend.python.lint.flake8 import rules as flake8_rules


def rules():
  return (
    *flake8_rules.rules(),
    *python_lint_target.rules(),
  )
