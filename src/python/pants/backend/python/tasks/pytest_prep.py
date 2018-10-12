# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import object

import pkg_resources
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.pex_info import PexInfo

from pants.backend.python.subsystems.pytest import PyTest
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.tasks.python_execution_task_base import PythonExecutionTaskBase


class PytestPrep(PythonExecutionTaskBase):
  """Prepares a PEX binary for the current test context with `py.test` as its entry-point."""

  class PytestBinary(object):
    """A `py.test` PEX binary with an embedded default (empty) `pytest.ini` config file."""

    _COVERAGE_PLUGIN_MODULE_NAME = '__{}__'.format(__name__.replace('.', '_'))

    def __init__(self, interpreter, pex):
      # Here we hack around `coverage.cmdline` nuking the 0th element of `sys.path` (our root pex)
      # by ensuring, the root pex is on the sys.path twice.
      # See: https://github.com/nedbat/coveragepy/issues/715
      pex_path = pex.path()
      pex_info = PexInfo.from_pex(pex_path)
      pex_info.merge_pex_path(pex_path)  # We're now on the sys.path twice.
      PEXBuilder(pex_path, interpreter=interpreter, pex_info=pex_info).freeze()
      self._pex = PEX(pex=pex_path, interpreter=interpreter)

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
    if not self.context.targets(lambda t: isinstance(t, PythonTests)):
      return
    pex_info = PexInfo.default()
    pex_info.entry_point = 'pytest'
    pytest_binary = self.create_pex(pex_info)
    interpreter = self.context.products.get_data(PythonInterpreter)
    self.context.products.register_data(self.PytestBinary,
                                        self.PytestBinary(interpreter, pytest_binary))
