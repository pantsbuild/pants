# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Autoformatter for Python unused/useless statements.

See https://www.pantsbuild.org/docs/python-linters-and-formatters and
https://github.com/myint/autoflake.
"""

from pants.backend.python.lint import python_fmt
from pants.backend.python.lint.autoflake import rules as autoflake_rules


def rules():
    return (*autoflake_rules.rules(), *python_fmt.rules())
