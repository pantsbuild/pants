# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""Python autoformatter for PEP257 docstring conventions.

See https://github.com/myint/docformatter.
"""

from pants.backend.python.lint import python_fmt
from pants.backend.python.lint.docformatter.rules import rules as docformatter_rules


def rules():
    return (*docformatter_rules(), *python_fmt.rules())
