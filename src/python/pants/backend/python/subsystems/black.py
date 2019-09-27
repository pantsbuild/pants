# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option


class Black(PythonToolBase):
  options_scope = 'black'
  default_requirements = ['black==19.3b0', 'setuptools']
  default_entry_point = 'black:patched_main'
  default_interpreter_constraints = ["CPython>=3.6"]

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--config', advanced=True, type=file_option, fingerprint=True,
              help="Path to formatting tool's config file")
