# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.graph_info.tasks.paths import Path, Paths
from pants.base.exceptions import TaskError
from pants_test.tasks.task_test_base import ConsoleTaskTestBase


class PathsTest(ConsoleTaskTestBase):

  @classmethod
  def task_type(cls):
    return Paths

  def test_only_one_target(self):
    target_a = self.make_target('a')
    with self.assertRaises(TaskError) as cm:
      self.execute_console_task(targets=[target_a])
    self.assertIn('Specify two targets please', str(cm.exception))
    self.assertIn('found 1', str(cm.exception))

  def test_three_targets(self):
    target_a = self.make_target('a')
    target_b = self.make_target('b')
    target_c = self.make_target('c')
    with self.assertRaises(TaskError) as cm:
      self.execute_console_task(targets=[target_a, target_b, target_c])
    self.assertIn('Specify two targets please', str(cm.exception))
    self.assertIn('found 3', str(cm.exception))

  def test_path_dependency_first_finds_no_paths(self):
    # Not sure if I like this behavior, but adding to document it
    target_b = self.make_target('b')
    target_a = self.make_target('a', dependencies=[target_b])

    self.assert_console_output('Found 0 paths', targets=[target_b, target_a])

  def test_single_edge_path(self):
    target_b = self.make_target('b')
    target_a = self.make_target('a', dependencies=[target_b])


    self.assert_console_output('Found 1 path',
                               '',
                               '\t[a, b]',
                               targets=[target_a, target_b])

  def test_same_target_path(self):
    target_b = self.make_target('b')

    self.assert_console_output('Found 1 path',
                               '',
                               '\t[b]',
                               targets=[target_b, target_b])

  def test_two_paths(self):
    target_b = self.make_target('b')
    target_inner_1 = self.make_target('inner1', dependencies=[target_b])
    target_inner_2 = self.make_target('inner2', dependencies=[target_b])
    target_a = self.make_target('a', dependencies=[target_inner_1, target_inner_2])


    self.assert_console_output('Found 2 paths',
                               '',
                               '\t[a, inner1, b]',
                               '\t[a, inner2, b]',
                               targets=[target_a, target_b])

  def test_cycle_no_path(self):
    target_b = self.make_target('b')
    target_inner_1 = self.make_target('inner1')
    target_inner_2 = self.make_target('inner2', dependencies=[target_inner_1])
    target_a = self.make_target('a', dependencies=[target_inner_1])
    target_inner_1.inject_dependency(target_inner_2.address)

    self.assert_console_output('Found 0 paths',
                               targets=[target_a, target_b])

  def test_cycle_path(self):
    target_b = self.make_target('b')
    target_inner_1 = self.make_target('inner1', dependencies=[target_b])
    target_inner_2 = self.make_target('inner2', dependencies=[target_inner_1, target_b])
    target_inner_1.inject_dependency(target_inner_2.address)
    target_a = self.make_target('a', dependencies=[target_inner_1])

    self.assert_console_output('Found 3 paths',
                               '',
                               '\t[a, inner1, b]',
                               '\t[a, inner1, inner2, b]',
                               '\t[a, inner1, inner2, inner1, b]',
                               targets=[target_a, target_b])

  def test_overlapping_paths(self):
    target_b = self.make_target('b')
    target_inner_1 = self.make_target('inner1', dependencies=[target_b])
    target_inner_2 = self.make_target('inner2', dependencies=[target_inner_1])
    target_a = self.make_target('a', dependencies=[target_inner_1, target_inner_2])

    self.assert_console_output('Found 2 paths',
                               '',
                               '\t[a, inner1, b]',
                               '\t[a, inner2, inner1, b]',
                               targets=[target_a, target_b])


class PathTest(ConsoleTaskTestBase):

  @classmethod
  def task_type(cls):
    return Path

  def test_only_returns_first_path(self):
    target_b = self.make_target('b')
    target_inner_1 = self.make_target('inner1', dependencies=[target_b])
    target_inner_2 = self.make_target('inner2', dependencies=[target_inner_1])
    target_a = self.make_target('a', dependencies=[target_inner_1, target_inner_2])

    self.assert_console_output('[a, inner1, b]',
                               targets=[target_a, target_b])

  def test_when_no_path(self):
    target_b = self.make_target('b')
    target_a = self.make_target('a')

    self.assert_console_output('No path found from a to b!',
                               targets=[target_a, target_b])
