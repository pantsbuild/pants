# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.lint import python_linter
from pants.backend.python.lint.pylint import rules as pylint_rules


def rules():
    return (
        *pylint_rules.rules(),
        *python_linter.rules(),
    )
