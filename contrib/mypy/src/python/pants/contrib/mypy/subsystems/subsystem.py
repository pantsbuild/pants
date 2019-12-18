# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Tuple

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.option.custom_types import file_option
from pants.option.option_util import flatten_shlexed_list


class MyPy(PythonToolBase):
  options_scope = 'mypy'
  default_version = 'mypy==0.740'
  default_entry_point = 'mypy'
  default_interpreter_constraints = ["CPython>=3.5"]

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register(
      '--args', type=list, member_type=str,
      help="Arguments to pass directly to mypy, e.g. "
           "`--mypy-args=\"--python-version 3.7 --disallow-any-expr\"`",
    )
    register(
      '--config', type=file_option,
      help="Path to `mypy.ini` or alternative MyPy config file"
    )

  def get_args(self) -> Tuple[str, ...]:
    return flatten_shlexed_list(self.get_options().args)
