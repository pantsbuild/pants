# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pex.pex_info import PexInfo

from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.tasks2.python_execution_task_base import PythonExecutionTaskBase


class PytestPrep(PythonExecutionTaskBase):
  """Prepares pex binaries for the current test context with py.test as its entry-point."""

  PYTEST_BINARIES = 'pytest_binaries'

  @classmethod
  def product_types(cls):
    return [cls.PYTEST_BINARIES]

  @classmethod
  def subsystem_dependencies(cls):
    return super(PytestPrep, cls).subsystem_dependencies() + (PyTest,)

  def extra_requirements(self):
    return PyTest.global_instance().get_requirement_strings()

  def execute(self):
    pex_info = PexInfo.default()
    pex_info.entry_point = 'pytest'
    pytest_binaries = self.context.products.register_data(self.PYTEST_BINARIES, {})
    for partition_name in self.target_roots_partitions():
      pytest_binaries[partition_name] = {}
      for targets_subset in target_roots_subsets(partition_name):
         pytest_binaries[partition_name][targets_subset] = self.create_pex(
             targets, pex_info=pex_info)
