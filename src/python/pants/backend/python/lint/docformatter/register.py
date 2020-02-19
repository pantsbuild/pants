# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.lint import python_format_target, python_lint_target
from pants.backend.python.lint.docformatter.rules import rules as docformatter_rules


def rules():
  return (*docformatter_rules(), *python_format_target.rules(), *python_lint_target.rules())
