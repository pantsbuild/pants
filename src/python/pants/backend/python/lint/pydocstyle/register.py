# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Static analysis tool for checking compliance with Python docstring conventions.

See https://www.pantsbuild.org/docs/python-linters-and-formatters and
http://www.pydocstyle.org/en/stable/.
"""

from pants.backend.python.lint.pydocstyle import rules as pydocstyle_rules
from pants.backend.python.lint.pydocstyle import skip_field, subsystem


def rules():
    return (*pydocstyle_rules.rules(), *skip_field.rules(), *subsystem.rules())
