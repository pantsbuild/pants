# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Type checker for Python.

See https://pants.readme.io/docs/python-linters-and-formatters and
https://mypy.readthedocs.io/en/stable/.
"""

from pants.backend.python.lint.mypy import rules as mypy_rules


def rules():
    return mypy_rules.rules()
