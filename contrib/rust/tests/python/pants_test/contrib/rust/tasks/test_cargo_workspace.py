# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import collections

from pants_test.task_test_base import TaskTestBase

from pants.contrib.rust.tasks.cargo_workspace import Workspace


class CargoTaskWorkspace(TaskTestBase):
  class TestCargoWorkspace(Workspace):

    def execute(self):
      raise NotImplementedError()

  @classmethod
  def task_type(cls):
    return cls.TestCargoWorkspace

  def test_is_target_a_member_true(self):
    task = self.create_task(self.context())
    target_name = 'a'
    member_names = ['a', 'b', 'c']

    self.assertTrue(task.is_target_a_member(target_name, member_names))

  def test_is_target_a_member_false(self):
    task = self.create_task(self.context())
    target_name = 'd'
    member_names = ['a', 'b', 'c']

    self.assertFalse(task.is_target_a_member(target_name, member_names))

  def test_is_lib_or_bin_target_true(self):
    TargetDefinition = collections.namedtuple('TargetDefinition', 'kind')
    targets = [TargetDefinition('bin'),
               TargetDefinition('lib'),
               TargetDefinition('cdylib'),
               TargetDefinition('rlib'),
               TargetDefinition('dylib'),
               TargetDefinition('staticlib'),
               TargetDefinition('proc-macro')]

    task = self.create_task(self.context())

    result = list(map(lambda target: task.is_lib_or_bin_target(target), targets))
    self.assertListEqual([True] * len(targets), result)

  def test_is_lib_or_bin_target_false(self):
    TargetDefinition = collections.namedtuple('TargetDefinition', 'kind')
    target = TargetDefinition('test')
    task = self.create_task(self.context())
    self.assertFalse(task.is_lib_or_bin_target(target))

  def test_is_test_target_true(self):
    TargetDefinition = collections.namedtuple('TargetDefinition', 'kind, compile_mode')
    targets = [TargetDefinition('test', '_'),
               TargetDefinition('test', 'test'),
               TargetDefinition('_', 'test')]

    task = self.create_task(self.context())
    result = list(map(lambda target: task.is_test_target(target), targets))
    self.assertListEqual([True] * len(targets), result)

  def test_is_test_target_false(self):
    TargetDefinition = collections.namedtuple('TargetDefinition', 'kind, compile_mode')
    targets = [TargetDefinition('bin', 'build'),
               TargetDefinition('lib', 'build'),
               TargetDefinition('cdylib', 'build'),
               TargetDefinition('rlib', 'build'),
               TargetDefinition('rlib', 'build'),
               TargetDefinition('dylib', 'build'),
               TargetDefinition('staticlib', 'build'),
               TargetDefinition('proc-macro', 'build')]

    task = self.create_task(self.context())
    result = list(map(lambda target: task.is_test_target(target), targets))
    self.assertListEqual([False] * len(targets), result)

# def is_workspace_member(self, target_definition, workspace_target):
# def inject_member_target(self, target_definition, workspace_target):
# def inject_synthetic_of_original_target_into_build_graph(self, synthetic_target, original_target):
# def get_member_sources_files(self, member_definition):
