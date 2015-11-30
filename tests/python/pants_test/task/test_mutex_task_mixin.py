# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
from contextlib import contextmanager

from pants.build_graph.target import Target
from pants.task.mutex_task_mixin import MutexTaskMixin
from pants.util.contextutil import temporary_dir
from pants_test.base_test import BaseTest


class LogViewerTaskMixin(MutexTaskMixin):
  @classmethod
  def mutex_base(cls):
    return LogViewerTaskMixin

  def __init__(self, *args, **kwargs):
    super(LogViewerTaskMixin, self).__init__(*args, **kwargs)

    self._executed = None

  @property
  def executed(self):
    return self._executed

  def execute_for(self, targets):
    self._executed = targets


class RedTarget(Target):
  pass


class RedLogViewer(LogViewerTaskMixin):
  options_scope = 'test_scope_red'

  @classmethod
  def select_targets(cls, target):
    return isinstance(target, RedTarget)


class BlueTarget(Target):
  pass


class BlueLogViewer(LogViewerTaskMixin):
  options_scope = 'test_scope_blue'

  @classmethod
  def select_targets(cls, target):
    return isinstance(target, BlueTarget)


class GreenTarget(Target):
  pass


class GreenLogViewer(LogViewerTaskMixin):
  options_scope = 'test_scope_green'

  @classmethod
  def select_targets(cls, target):
    return isinstance(target, GreenTarget)


class MutexTaskMixinTest(BaseTest):

  def tearDown(self):
    super(MutexTaskMixinTest, self).tearDown()

    LogViewerTaskMixin.reset_implementations()

  @contextmanager
  def mutex_group(self, targets=None):
    context = self.context(target_roots=targets,
                           for_task_types=[RedLogViewer, BlueLogViewer, GreenLogViewer])

    def prepare_task(task_type):
      task_type.prepare(self.options, round_manager=None)

    prepare_task(RedLogViewer)
    prepare_task(BlueLogViewer)
    prepare_task(GreenLogViewer)

    def create_task(workdir, task_type):
      return task_type(context, workdir)

    with temporary_dir() as red, temporary_dir() as blue, temporary_dir() as green:
      red_viewer = create_task(red, RedLogViewer)
      blue_viewer = create_task(blue, BlueLogViewer)
      green_viewer = create_task(green, GreenLogViewer)
      yield red_viewer, blue_viewer, green_viewer

  def test_one(self):
    red = self.make_target('red', RedTarget)
    with self.mutex_group(targets=[red]) as (red_viewer, blue_viewer, green_viewer):
      red_viewer.execute()
      blue_viewer.execute()
      green_viewer.execute()

      self.assertEqual([red], red_viewer.executed)
      self.assertIsNone(blue_viewer.executed)
      self.assertIsNone(green_viewer.executed)

  def assert_activation_error(self, error_type, viewer):
    with self.assertRaises(error_type):
      viewer.execute()
    self.assertIsNone(viewer.executed)

  def test_none(self):
    assert_no_activations = functools.partial(self.assert_activation_error,
                                              MutexTaskMixin.NoActivationsError)
    with self.mutex_group() as (red_viewer, blue_viewer, green_viewer):
      assert_no_activations(red_viewer)
      assert_no_activations(blue_viewer)
      assert_no_activations(green_viewer)

  def assert_incompatible_activations(self, viewer):
    self.assert_activation_error(MutexTaskMixin.IncompatibleActivationsError, viewer)

  def test_some_incompatible(self):
    red = self.make_target('red', RedTarget)
    blue = self.make_target('blue', BlueTarget)
    with self.mutex_group(targets=[red, blue]) as (red_viewer, blue_viewer, green_viewer):
      self.assert_incompatible_activations(red_viewer)
      self.assert_incompatible_activations(blue_viewer)

      green_viewer.execute()
      self.assertIsNone(green_viewer.executed)

  def test_all_incompatible(self):
    red = self.make_target('red', RedTarget)
    blue = self.make_target('blue', BlueTarget)
    green = self.make_target('green', GreenTarget)
    with self.mutex_group(targets=[red, blue, green]) as (red_viewer, blue_viewer, green_viewer):
      self.assert_incompatible_activations(red_viewer)
      self.assert_incompatible_activations(blue_viewer)
      self.assert_incompatible_activations(green_viewer)
