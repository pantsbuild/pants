# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import textwrap

import pytest
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase

from pants.contrib.python.checks.tasks.checkstyle.checker import PythonCheckStyleTask, PythonFile
from pants.contrib.python.checks.tasks.checkstyle.common import CheckstylePlugin
from pants.contrib.python.checks.tasks.checkstyle.plugin_subsystem_base import PluginSubsystemBase


class RageSubsystem(PluginSubsystemBase):
  options_scope = 'pycheck-Rage'

  def get_plugin_type(self):
    return Rage


class Rage(CheckstylePlugin):
  """Dummy Checkstyle plugin that hates everything"""

  def nits(self):
    """Return Nits for everything you see."""
    for line_no, _ in self.python_file.enumerate():
      yield self.error('T999', 'I hate everything!', line_no)


@pytest.fixture()
def no_qa_line(request):
  """Py Test fixture to create a testing file for single line filters"""
  request.cls.no_qa_line = PythonFile.from_statement(textwrap.dedent("""
    print('This is not fine')
    print('This is fine')  # noqa"""))


@pytest.fixture()
def no_qa_file(request):
  """Py Test fixture to create a testing file for whole file filters"""
  request.cls.no_qa_file = PythonFile.from_statement(textwrap.dedent("""
      # checkstyle: noqa
      print('This is not fine')
      print('This is fine')"""))


@pytest.mark.usefixtures('no_qa_file', 'no_qa_line')
class TestPyStyleTask(PythonTaskTestBase):
  @classmethod
  def task_type(cls):
    """Required method"""
    return PythonCheckStyleTask

  def _create_task(self):
    # Interpreter required by PythonTaskTestBase
    self.set_options(interpreter='python')
    return self.create_task(self.context())

  def setUp(self):
    """Setup PythonCheckStyleTask with Rage Checker"""
    super(TestPyStyleTask, self).setUp()
    PythonCheckStyleTask.clear_plugins()
    PythonCheckStyleTask.register_plugin(name='angry_test', subsystem=RageSubsystem)

    self.style_check = self._create_task()
    self.style_check.options.suppress = None

  def test_noqa_line_filter_length(self):
    """Verify the number of lines filtered is what we expect"""
    nits = list(self.style_check.get_nits(self.no_qa_line))
    self.assertEqual(1, len(nits), ('Actually got nits: {}'.format(
      ' '.join('{}:{}'.format(nit._line_number, nit) for nit in nits)
    )))

  def test_noqa_line_filter_code(self):
    """Verify that the line we see has the correct code"""
    nits = list(self.style_check.get_nits(self.no_qa_line))
    self.assertEqual('T999', nits[0].code, 'Not handling the code correctly')

  def test_noqa_file_filter(self):
    """Verify Whole file filters are applied correctly"""
    nits = list(self.style_check.get_nits(self.no_qa_file))
    self.assertEqual(0, len(nits), 'Expected zero nits since entire file should be ignored')
