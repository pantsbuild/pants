# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Type checker for Python.

See https://www.pantsbuild.org/docs/python-linters-and-formatters and
https://mypy.readthedocs.io/en/stable/.
"""

from pants.backend.python.typecheck.mypy import mypyc
from pants.backend.python.typecheck.mypy import rules as mypy_rules
from pants.backend.python.typecheck.mypy import skip_field, subsystem


def rules():
    return (*mypy_rules.rules(), *mypyc.rules(), *skip_field.rules(), *subsystem.rules())
