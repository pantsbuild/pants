# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import textwrap
from collections import namedtuple

import pytest

from pants.backend.python.tasks.checkstyle.checker import PythonCheckStyleTask, PythonFile
from pants.backend.python.tasks.checkstyle.common import CheckstylePlugin
from pants.subsystem.subsystem import Subsystem
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase


class RageSubsystem(Subsystem):
  options_scope = 'pycheck-Rage'
  @classmethod
  def register_options(cls, register):
    super(Subsystem, cls).register_options(register)
    register('--skip', default=False, action='store_true',
             help='If enabled, skip this style checker.')

class Rage(CheckstylePlugin):
  """Dummy Checkstyle plugin that hates everything"""
  subsystem = RageSubsystem

  def __init__(self, python_file):
    self.python_file = python_file

  def nits(self):
    """Return Nits for everything you see"""
    for line_no, _ in self.python_file.enumerate():
      yield self.error('T999', 'I hate everything!', line_no)


@pytest.fixture()
def no_qa_line(request):
  """Py Test fixture to create a testing file for single line filters"""
  request.cls.no_qa_line = PythonFile.from_statement(textwrap.dedent("""
    print('This is not fine')
    print('This is fine')  # noqa
  """))


@pytest.fixture()
def no_qa_file(request):
  """Py Test fixture to create a testing file for whole file filters"""
  request.cls.no_qa_file = PythonFile.from_statement(textwrap.dedent("""
      # checkstyle: noqa
      print('This is not fine')
      print('This is fine')
  """))


@pytest.mark.usefixtures('no_qa_file', 'no_qa_line')
class TestPyStyleTask(PythonTaskTestBase):
  @classmethod
  def task_type(cls):
    """Required method"""
    return PythonCheckStyleTask

  def _create_context(self, target_roots=None, for_task_types=None):
    return self.context(
      options={
        'py.check': {
          'interpreter': 'python'  # Interpreter required by PythonTaskTestBase
        }
      },
      target_roots=target_roots, for_task_types=for_task_types)

  def setUp(self):
    """Setup PythonCheckStyleTask with Rage Checker"""
    super(TestPyStyleTask, self).setUp()
    PythonCheckStyleTask.clear_plugins()
    PythonCheckStyleTask.register_plugin(name='angry_test', checker=Rage)
    PythonCheckStyleTask.options_scope = 'py.check'

    self.style_check = PythonCheckStyleTask(self._create_context(
                                            for_task_types=[PythonCheckStyleTask]), '.')
    self.style_check.options.suppress = None

  def test_noqa_line_filter_length(self):
    """Verify the number of lines filtered is what we expect"""
    nits = list(self.style_check.get_nits(self.no_qa_line))
    assert len(nits) == 1, ('Actually got nits: {}'.format(
      ' '.join('{}:{}'.format(nit._line_number, nit) for nit in nits)
    ))

  def test_noqa_line_filter_code(self):
    """Verify that the line we see has the correct code"""
    nits = list(self.style_check.get_nits(self.no_qa_line))
    assert nits[0].code == 'T999', 'Not handling the code correctly'

  def test_noqa_file_filter(self):
    """Verify Whole file filters are applied correctly"""
    nits = list(self.style_check.get_nits(self.no_qa_file))
    assert len(nits) == 0, 'Expected zero nits since entire file should be ignored'
