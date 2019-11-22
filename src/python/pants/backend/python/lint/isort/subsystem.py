# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option


class Isort(PythonToolBase):
  options_scope = 'isort'
  default_requirements = ['isort==4.3.20', 'setuptools']
  default_entry_point = 'isort.main'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register(
      '--config', type=file_option, default=None,
      help="Path to `isort.cfg` or alternative isort config file"
    )
