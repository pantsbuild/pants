# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option
from pants.option.option_util import flatten_shlexed_list


class Flake8(PythonToolBase):
  options_scope = 'flake8'
  default_version = 'flake8'
  default_extra_requirements = ['setuptools']
  default_entry_point = 'flake8'
  default_interpreter_constraints = ["CPython>=2.7,<3", "CPython>=3.4"]

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register(
      '--args', type=list, member_type=str,
      help="Arguments to pass directly to Flake8, e.g. "
           "`--flake8-args=\"--ignore E123,W456 --enable-extensions H111\"`",
    )
    register(
      '--config', type=file_option, default=None, advanced=True,
      help="Path to `.flake8` or alternative Flake8 config file"
    )

  def get_args(self) -> Tuple[str, ...]:
    return flatten_shlexed_list(self.get_options().args)
