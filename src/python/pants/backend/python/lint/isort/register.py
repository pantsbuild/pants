# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Autoformatter for Python import statements.

See https://www.pantsbuild.org/docs/python-linters-and-formatters and
https://timothycrosley.github.io/isort/.
"""

from pants.backend.python.lint import python_fmt
from pants.backend.python.lint.isort import rules as isort_rules
from pants.backend.python.lint.isort import skip_field


def rules():
    return (*isort_rules.rules(), *python_fmt.rules(), *skip_field.rules())
