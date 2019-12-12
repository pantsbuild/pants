# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.lint import formattable_python_target
from pants.backend.python.lint.isort import rules as isort_rules


def rules():
  return (
    *isort_rules.rules(),
    *formattable_python_target.rules(),
  )
