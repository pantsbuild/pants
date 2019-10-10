# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.option.custom_types import file_option
from pants.subsystem.subsystem import Subsystem
from pants.util.objects import enum


class PythonFormattingTool(enum([
  "black",
  "black_with_two_spaces_indent",
  ])): pass


class PythonFormatter(Subsystem):
  options_scope = 'python_fmt'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--tool',
             advanced=True,
             type=PythonFormattingTool,
             default=PythonFormattingTool.black,
             fingerprint=True,
             help="Path to formatting tool's config file")
