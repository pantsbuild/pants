# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option
from pants.option.option_util import flatten_shlexed_list


class Isort(PythonToolBase):
  options_scope = 'isort'
  default_version = 'isort==4.3.20'
  default_extra_requirements = ['setuptools']
  default_entry_point = 'isort.main'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register(
      '--args', type=list, member_type=str,
      help="Arguments to pass directly to isort, e.g. "
           "`--isort-args=\"--case-sensitive --trailing-comma\"`",
    )
    register(
      '--config', type=list, member_type=file_option,
      help="Path to `isort.cfg` or alternative isort config file(s)"
    )

  def get_args(self) -> Tuple[str, ...]:
    return flatten_shlexed_list(self.get_options().args)
