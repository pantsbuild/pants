# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.build_graph.target_filter_subsystem import TargetFilter, TargetFiltering
from pants.task.task import Task
from pants_test.task_test_base import TaskTestBase


class TestTargetFilter(TaskTestBase):

  class DummyTask(Task):
    options_scope = 'dummy'

    def execute(self):
      self.context.products.safe_create_data('task_targets', self.get_targets)

  @classmethod
  def task_type(cls):
    return cls.DummyTask

  def test_task_execution_with_filter(self):
    a = self.make_target('a', tags=['skip-me'])
    b = self.make_target('b', dependencies=[a], tags=[])

    context = self.context(for_task_types=[self.DummyTask], for_subsystems=[TargetFilter], target_roots=[b], options={
      TargetFilter.options_scope: {
        'exclude_tags': ['skip-me']
      }
    })

    self.create_task(context).execute()
    self.assertEqual([b], context.products.get_data('task_targets'))

  def test_filtering_single_tag(self):
    a = self.make_target('a', tags=[])
    b = self.make_target('b', tags=['skip-me'])
    c = self.make_target('c', tags=['tag1', 'skip-me'])

    filtered_targets = TargetFiltering([a, b, c], {'skip-me'}).apply_tag_blacklist()
    self.assertEqual([a], filtered_targets)

  def test_filtering_multiple_tags(self):
    a = self.make_target('a', tags=['tag1', 'skip-me'])
    b = self.make_target('b', tags=['tag1', 'tag2', 'skip-me'])
    c = self.make_target('c', tags=['tag2'])

    filtered_targets = TargetFiltering([a, b, c], {'skip-me', 'tag2'}).apply_tag_blacklist()
    self.assertEqual([], filtered_targets)

  def test_filtering_no_tags(self):
    a = self.make_target('a', tags=['tag1'])
    b = self.make_target('b', tags=['tag1', 'tag2'])
    c = self.make_target('c', tags=['tag2'])

    filtered_targets = TargetFiltering([a, b, c], set()).apply_tag_blacklist()
    self.assertEqual([a, b, c], filtered_targets)
