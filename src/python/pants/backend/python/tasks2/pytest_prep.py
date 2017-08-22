# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pex.pex_info import PexInfo

from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.tasks2.python_execution_task_base import PythonExecutionTaskBase


class PytestPrep(PythonExecutionTaskBase):
  """Prepares a pex binary for the current test context with py.test as its entry-point."""

  PYTEST_BINARY = 'pytest_binary'

  @classmethod
  def product_types(cls):
    return [cls.PYTEST_BINARY]

  @classmethod
  def subsystem_dependencies(cls):
    return super(PytestPrep, cls).subsystem_dependencies() + (PyTest,)

  def extra_requirements(self):
    return PyTest.global_instance().get_requirement_strings()

  def execute(self):
    pex_info = PexInfo.default()
    pex_info.entry_point = 'pytest'
    pytest_binary = self.create_pex(pex_info)
    self.context.products.register_data(self.PYTEST_BINARY, pytest_binary)
