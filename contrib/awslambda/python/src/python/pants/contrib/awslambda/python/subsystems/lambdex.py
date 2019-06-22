# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase


class Lambdex(PythonToolBase):
  options_scope = 'lambdex'
  default_requirements = [
    'lambdex==0.1.3',

    # TODO(John Sirois): Remove when we can upgrade to a version of lambdex with
    # https://github.com/wickman/lambdex/issues/6 fixed.
    'setuptools==40.8.0'
  ]
  default_entry_point = 'lambdex.bin.lambdex'
