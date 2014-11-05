# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

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

    # Create a synthetic subclass of the task type, with a unique scope, to ensure
    # proper test isolation (unfortunately we currently rely on class-level state in Task.)
    # TODO: Get rid of this once we re-do the Task lifecycle.
    self.options_scope = str(uuid.uuid4())
    subclass_name = b'test_{0}_{1}'.format(self.task_type().__name__, self.options_scope)
    self._testing_task_type = type(subclass_name, (self.task_type(),),
                                   {'options_scope': self.options_scope})

  def set_new_options(self, **kwargs):
    self.set_new_options_for_scope(self.options_scope, **kwargs)

  def context(self, config='', options=None, new_options=None, target_roots=None, **kwargs):
    # Add in our task type.
    return super(TaskTestBase, self).context(for_task_types=[self._testing_task_type],
                                             config=config,
                                             options=options,
                                             new_options=new_options,
                                             target_roots=target_roots,
                                             **kwargs)

  def create_task(self, context, workdir):
    return self._testing_task_type(context, workdir)
