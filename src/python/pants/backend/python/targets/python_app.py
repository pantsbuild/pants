# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.python.targets.python_binary import PythonBinary
from pants.build_graph.app_base import AppBase


class PythonApp(AppBase):
  @classmethod
  def alias(cls):
    return 'python_app'

  @classmethod
  def binary_target_type(cls):
    return PythonBinary

  @staticmethod
  def is_python_app(target):
    return isinstance(target, PythonApp)
