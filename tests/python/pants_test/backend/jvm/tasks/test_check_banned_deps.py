# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.jvm.dependency_constraints import DependencyConstraints, TargetName
# from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.targets.jvm_binary import JvmBinary
from pants.backend.jvm.tasks.check_banned_deps import CheckBannedDeps
from pants_test.task_test_base import TaskTestBase


class CheckBannedDepsTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return CheckBannedDeps

  def _target(self, name, dependencies=None, constraints=None, **kwargs):
    return self.make_target(
      spec=":{}".format(name),
      target_type=JvmBinary,
      make_missing_sources=True,
      dependencies=dependencies or [],
      dependency_constraints=DependencyConstraints(constraints or []),
      **kwargs
    )

  # TODO Assigning IDs like this is clunky
  def _t(self, dependencies=None, constraints=None, id='', **kwargs):
    return self._target("T{}".format(id), dependencies, constraints, **kwargs)

  def _d(self, id, dependencies=None, constraints=None, **kwargs):
    return self._target("D{}".format(id), dependencies, constraints, **kwargs)

  def _check_run_logs(self, targets, error_number):
    context = self.context(target_roots=targets)
    task = self.create_task(context)
    errors = task.check_graph()
    self.assertEqual(len(errors), error_number)

  def _check_fails(self, targets, error_number):
    self._check_run_logs(targets, error_number)

  def _check_succeeds(self, targets):
    self._check_run_logs(targets, 0)

  def test_direct_dependency(self):
    """If T depends on D1 and T bans D1, T should fail."""
    graph = self._t(
      [self._d(1)],
      [TargetName(":D1")]
    )
    self._check_fails([graph], 1)

  def test_dependency_bans_target(self):
    """If T depends on D1, and D1 bans T, T should fail."""
    graph = self._t(
      [self._d(1, [], [TargetName(":T")])],
    )
    self._check_fails([graph], 1)

  def test_constraints_in_unrelated_targets(self):
    """If T depends on D1 and D2, and D1 bans D2, T should fail."""
    graph = self._t([
      self._d(1, [], [TargetName(":D2")]),
      self._d(2)
    ])
    self._check_fails([graph], 1)

  def test_multiple_roots(self):
    """If T1 bans a dependency of T2, checking both should not fail"""
    graph = [
      self._t([self._d(1)], id="1"),
      self._t([], [TargetName(":D1")], id="2"),
    ]
    self._check_succeeds(graph)

  def test_multiple_errors(self):
    """If T bans two dependencies, two errors should trigger"""
    graph = [self._t([
      self._d(1, [
        self._d(2)
      ]),
      self._d(3)
    ], [
      TargetName(":D1"),
      TargetName(":D2")
    ])]

    self._check_fails(graph, 2)
