# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import tempfile
import uuid

from pants_test.base_test import BaseTest


class TaskTestBase(BaseTest):
  """A baseclass useful for testing a single Task type.

  TODO: Merge this with pants_test.tasks.test_base.TaskTest.  This is a major refactor, however,
        as different tasks create Context and Task instances in different ways. We need to
        have one uniform way of creating these things and make all tests use that.
        However this will be a lot easier after we migrate to the new options system, as many
        of the differences involve config and options.
  """

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

  def context(self, config='', options=None, target_roots=None, **kwargs):
    # Add in our task type.
    return super(TaskTestBase, self).context(for_task_types=[self._testing_task_type],
                                             config=config,
                                             options=options,
                                             target_roots=target_roots,
                                             **kwargs)

  def create_task(self, context, workdir=None):
    return self._testing_task_type(context, workdir or self._test_workdir)
