# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.lint.flake8 import rules as flake8_rules
from pants.backend.python.targets import formattable_python_target


def rules():
  return (
    *flake8_rules.rules(),
    *formattable_python_target.rules(),
  )
