# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

import pkg_resources
from pex.pex_info import PexInfo

from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.tasks.python_execution_task_base import PythonExecutionTaskBase


class PytestPrep(PythonExecutionTaskBase):
  """Prepares a PEX binary for the current test context with `py.test` as its entry-point."""

  class PytestBinary(object):
    """A `py.test` PEX binary with an embedded default (empty) `pytest.ini` config file."""

    _COVERAGE_PLUGIN_MODULE_NAME = '__{}__'.format(__name__.replace('.', '_'))

    def __init__(self, pex):
      self._pex = pex

    @property
    def pex(self):
      """Return the loose-source py.test binary PEX.

      :rtype: :class:`pex.pex.PEX`
      """
      return self._pex

    @property
    def config_path(self):
      """Return the absolute path of the `pytest.ini` config file in this py.test binary.

      :rtype: str
      """
      return os.path.join(self._pex.path(), 'pytest.ini')

    @classmethod
    def coverage_plugin_module(cls):
      """Return the name of the coverage plugin module embedded in this py.test binary.

      :rtype: str
      """
      return cls._COVERAGE_PLUGIN_MODULE_NAME

  @classmethod
  def implementation_version(cls):
    return super(PytestPrep, cls).implementation_version() + [('PytestPrep', 2)]

  @classmethod
  def product_types(cls):
    return [cls.PytestBinary]

  @classmethod
  def subsystem_dependencies(cls):
    return super(PytestPrep, cls).subsystem_dependencies() + (PyTest,)

  def extra_requirements(self):
    return PyTest.global_instance().get_requirement_strings()

  def extra_files(self):
    yield self.ExtraFile.empty('pytest.ini')
    yield self.ExtraFile(path='{}.py'.format(self.PytestBinary.coverage_plugin_module()),
                         content=pkg_resources.resource_string(__name__, 'coverage/plugin.py'))

  def execute(self):
    pex_info = PexInfo.default()
    pex_info.entry_point = 'pytest'
    pytest_binary = self.create_pex(pex_info)
    self.context.products.register_data(self.PytestBinary, self.PytestBinary(pytest_binary))
