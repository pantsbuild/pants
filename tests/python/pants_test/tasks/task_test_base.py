# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess
import tempfile
import uuid
from contextlib import closing
from StringIO import StringIO

from pants.backend.core.tasks.console_task import ConsoleTask
from pants.goal.goal import Goal
from pants_test.base_test import BaseTest


# TODO: Find a better home for this?
def is_exe(name):
  result = subprocess.call(['which', name], stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT)
  return result == 0


class TaskTestBase(BaseTest):
  """A baseclass useful for testing a single Task type."""

  @classmethod
  def task_type(cls):
    """Subclasses must return the type of the Task subclass under test."""
    raise NotImplementedError()

  def setUp(self):
    super(TaskTestBase, self).setUp()
    self._testing_task_type, self.options_scope = self.synthesize_task_subtype(self.task_type())
    # We locate the workdir below the pants_workdir, which BaseTest locates within
    # the BuildRoot.
    self._tmpdir = tempfile.mkdtemp(dir=self.pants_workdir)
    self._test_workdir = os.path.join(self._tmpdir, 'workdir')
    os.mkdir(self._test_workdir)

  @property
  def test_workdir(self):
    return self._test_workdir

  def synthesize_task_subtype(self, task_type):
    """Creates a synthetic subclass of the task type.

    The returned type has a unique options scope, to ensure proper test isolation (unfortunately
    we currently rely on class-level state in Task.)

    # TODO: Get rid of this once we re-do the Task lifecycle.

    :param task_type: The task type to subtype.
    :return: A pair (type, options_scope)
    """
    options_scope = uuid.uuid4().hex
    subclass_name = b'test_{0}_{1}'.format(task_type.__name__, options_scope)
    return type(subclass_name, (task_type,), {'options_scope': options_scope}), options_scope

  def set_options(self, **kwargs):
    self.set_options_for_scope(self.options_scope, **kwargs)

  def context(self, for_task_types=None, options=None, target_roots=None,
              console_outstream=None, workspace=None):
    # Add in our task type.
    for_task_types = [self._testing_task_type] + (for_task_types or [])
    return super(TaskTestBase, self).context(for_task_types=for_task_types,
                                             options=options,
                                             target_roots=target_roots,
                                             console_outstream=console_outstream,
                                             workspace=workspace)

  def create_task(self, context, workdir=None):
    return self._testing_task_type(context, workdir or self._test_workdir)


class ConsoleTaskTestBase(TaskTestBase):
  """A base class useful for testing ConsoleTasks."""

  def setUp(self):
    Goal.clear()
    super(ConsoleTaskTestBase, self).setUp()

    task_type = self.task_type()
    assert issubclass(task_type, ConsoleTask), \
        'task_type() must return a ConsoleTask subclass, got %s' % task_type

  def execute_task(self, targets=None, options=None):
    """Creates a new task and executes it with the given config, command line args and targets.

    :param targets: Optional list of Target objects passed on the command line.
    Returns the text output of the task.
    """
    options = options or {}
    with closing(StringIO()) as output:
      self.set_options(**options)
      context = self.context(target_roots=targets, console_outstream=output)
      task = self.create_task(context)
      task.execute()
      return output.getvalue()

  def execute_console_task(self, targets=None, extra_targets=None, options=None, workspace=None):
    """Creates a new task and executes it with the given config, command line args and targets.

    :param options: option values.
    :param targets: optional list of Target objects passed on the command line.
    :param extra_targets: optional list of extra targets in the context in addition to those
                          passed on the command line.
    :param workspace: optional Workspace to pass into the context.

    Returns the list of items returned from invoking the console task's console_output method.
    """
    options = options or {}
    self.set_options(**options)
    context = self.context(target_roots=targets, workspace=workspace)
    task = self.create_task(context)
    return list(task.console_output(list(task.context.targets()) + list(extra_targets or ())))

  def assert_entries(self, sep, *output, **kwargs):
    """Verifies the expected output text is flushed by the console task under test.

    NB: order of entries is not tested, just presence.

    sep:      the expected output separator.
    *output:  the output entries expected between the separators
    **options: additional options passed to execute_task.
    """
    # We expect each output line to be suffixed with the separator, so for , and [1,2,3] we expect:
    # '1,2,3,' - splitting this by the separator we should get ['1', '2', '3', ''] - always an extra
    # empty string if the separator is properly always a suffix and not applied just between
    # entries.
    self.assertEqual(sorted(list(output) + ['']), sorted((self.execute_task(**kwargs)).split(sep)))

  def assert_console_output(self, *output, **kwargs):
    """Verifies the expected output entries are emitted by the console task under test.

    NB: order of entries is not tested, just presence.

    *output:  the expected output entries
    **kwargs: additional kwargs passed to execute_console_task.
    """
    self.assertEqual(sorted(output), sorted(self.execute_console_task(**kwargs)))

  def assert_console_output_ordered(self, *output, **kwargs):
    """Verifies the expected output entries are emitted by the console task under test.

    NB: order of entries is tested.

    *output:  the expected output entries in expected order
    **kwargs: additional kwargs passed to execute_console_task.
    """
    self.assertEqual(list(output), self.execute_console_task(**kwargs))

  def assert_console_raises(self, exception, **kwargs):
    """Verifies the expected exception is raised by the console task under test.

    **kwargs: additional kwargs are passed to execute_console_task.
    """
    with self.assertRaises(exception):
      self.execute_console_task(**kwargs)
