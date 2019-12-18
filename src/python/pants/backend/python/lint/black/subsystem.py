# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option
from pants.option.option_util import flatten_shlexed_list


class Black(PythonToolBase):
  options_scope = 'black'
  default_version = 'black==19.3b0'
  default_extra_requirements = ['setuptools']
  default_entry_point = 'black:patched_main'
  default_interpreter_constraints = ["CPython>=3.6"]

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register(
      '--args', type=list, member_type=str,
      help="Arguments to pass directly to Black, e.g. "
           "`--black-args=\"--target-version=py37 --quiet\"`",
    )
    register(
      '--config', type=file_option, default=None, advanced=True,
      help="Path to Black's pyproject.toml config file"
    )

  def get_args(self) -> Tuple[str, ...]:
    return flatten_shlexed_list(self.get_options().args)
