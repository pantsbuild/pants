# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Python autoformatter for PEP257 docstring conventions.

See https://www.pantsbuild.org/docs/python-linters-and-formatters and
https://github.com/myint/docformatter.
"""

from pants.backend.python.lint import python_fmt
from pants.backend.python.lint.docformatter import skip_field, subsystem
from pants.backend.python.lint.docformatter.rules import rules as docformatter_rules


def rules():
    return (*docformatter_rules(), *python_fmt.rules(), *skip_field.rules(), *subsystem.rules())
