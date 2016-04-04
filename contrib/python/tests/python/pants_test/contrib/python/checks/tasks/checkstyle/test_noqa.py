# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import textwrap

from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase

from pants.contrib.python.checks.tasks.checkstyle.checker import PythonCheckStyleTask, PythonFile
from pants.contrib.python.checks.tasks.checkstyle.common import CheckstylePlugin
from pants.contrib.python.checks.tasks.checkstyle.plugin_subsystem_base import PluginSubsystemBase


def dedent_wo_first_line(text):
  return textwrap.dedent('\n'.join(text.split('\n')[1:]))

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

    self.no_qa_line = 'no_qa_line.py'
    self.create_file(self.no_qa_line, dedent_wo_first_line("""
        print('This is not fine')
        print('This is fine')  # noqa"""))

    self.no_qa_file = "no_qa_file.py"
    self.create_file(self.no_qa_file, dedent_wo_first_line("""
        # checkstyle: noqa
        print('This is not fine')
        print('This is fine')"""))

  def tearDown(self):
    super(TestPyStyleTask, self).tearDown()
    PythonCheckStyleTask.clear_plugins()

  def test_noqa_line_filter_length(self):
    """Verify the number of lines filtered is what we expect"""
    nits = list(self.style_check.get_nits(self.no_qa_line))
    self.assertEqual(1, len(nits), ('Actually got nits: {}'.format(
      ' '.join('{}:{}'.format(nit.line_number, nit) for nit in nits)
    )))

  def test_noqa_line_filter_code(self):
    """Verify that the line we see has the correct code"""
    nits = list(self.style_check.get_nits(self.no_qa_line))
    self.assertEqual('T999', nits[0].code, 'Not handling the code correctly')

  def test_noqa_file_filter(self):
    """Verify Whole file filters are applied correctly"""
    nits = list(self.style_check.get_nits(self.no_qa_file))

    self.assertEqual(0, len(nits), 'Expected zero nits since entire file should be ignored')
