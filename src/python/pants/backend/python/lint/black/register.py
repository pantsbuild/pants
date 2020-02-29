# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.python.lint import python_formatter, python_linter
from pants.backend.python.lint.black import rules as black_rules


def rules():
    return (
        *black_rules.rules(),
        *python_formatter.rules(),
        *python_linter.rules(),
    )
