# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.lint.black import rules as black_rules
from pants.backend.python.targets import formattable_python_target


def rules():
  return (
    *black_rules.rules(),
    *formattable_python_target.rules(),
  )
