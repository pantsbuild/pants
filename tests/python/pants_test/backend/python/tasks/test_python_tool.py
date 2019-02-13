# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import glob
import os
import re

from pants.backend.python.subsystems.python_tool_base import PythonToolBase
from pants.backend.python.tasks.python_tool_prep_base import PythonToolInstance, PythonToolPrepBase
from pants.task.task import Task
from pants.util.collections import assert_single_element
from pants.util.contextutil import environment_as, temporary_dir
from pants_test.backend.python.tasks.python_task_test_base import PythonTaskTestBase


class Tool(PythonToolBase):
  options_scope = 'test-tool'
  default_requirements = [
    'pex==1.5.3',
  ]
  default_entry_point = 'pex.bin.pex:main'


class ToolInstance(PythonToolInstance):
  pass


class ToolPrep(PythonToolPrepBase):
  options_scope = 'tool-prep-task'
  tool_subsystem_cls = Tool
  tool_instance_cls = ToolInstance


class ToolTask(Task):
  options_scope = 'tool-task'

  @classmethod
  def prepare(cls, options, round_manager):
    super(ToolTask, cls).prepare(options, round_manager)
    round_manager.require_data(ToolPrep.tool_instance_cls)

  def execute(self):
    tool_for_pex = self.context.products.get_data(ToolPrep.tool_instance_cls)
    stdout, stderr, exit_code, _ = tool_for_pex.output(['--version'])
    assert '' == stderr
    assert re.match(r'.*\.pex 1.5.3', stdout)
    assert 0 == exit_code


class PythonToolPrepTest(PythonTaskTestBase):

  @classmethod
  def task_type(cls):
    return ToolTask

  def _assert_tool_execution_for_python_version(self, use_py3=True):
    scope_string = '3' if use_py3 else '2'
    constraint_string = 'CPython>=3' if use_py3 else 'CPython<3'
    tool_prep_type = self.synthesize_task_subtype(ToolPrep, 'tp_scope_py{}'.format(scope_string))
    context = self.context(for_task_types=[tool_prep_type], for_subsystems=[Tool], options={
      'test-tool': {
        'interpreter_constraints': [constraint_string],
      },
    })
    # XDG_CACHE_HOME overrides the location of the cache dir.
    with temporary_dir() as tmp_dir, environment_as(XDG_CACHE_HOME=tmp_dir):
      tool_prep_task = tool_prep_type(context, os.path.join(
        self.pants_workdir, 'tp_py{}'.format(scope_string)))
      tool_prep_task.execute()
      # Check that the tool is in an interpreter-specific subdir of the cache dir.
      constructed_tool_location_glob = os.path.join(
        tmp_dir, 'pants', 'python',
        'CPython-{}*'.format(scope_string),
        tool_prep_task.fingerprint,
        'test-tool-*.pex',
      )
      tool_location = assert_single_element(glob.glob(constructed_tool_location_glob))
      self.assertTrue(os.path.isdir(tool_location))

      # Check that the tool can be executed successfully.
      self.create_task(context).execute()
      pex_tool = context.products.get_data(ToolPrep.tool_instance_cls)
      self.assertTrue(pex_tool.interpreter.identity.matches(constraint_string))

  def test_tool_execution(self):
    """Test that python tools are fingerprinted by python interpreter."""
    self._assert_tool_execution_for_python_version(use_py3=True)
    self._assert_tool_execution_for_python_version(use_py3=False)
