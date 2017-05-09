# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.prepare_resources import PrepareResources
from pants.build_graph.resources import Resources
from pants.build_graph.target import Target
from pants.util.contextutil import temporary_dir
from pants_test.tasks.task_test_base import TaskTestBase


class PrepareResourcesTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return PrepareResources

  class NonJvmResourcesUsingTarget(Target):
    def __init__(self, *args, **kwargs):
      kwargs.pop('resources', None)
      super(PrepareResourcesTest.NonJvmResourcesUsingTarget, self).__init__(*args, **kwargs)

    @property
    def has_resources(self):
      raise AssertionError('Non-JvmTarget resources query methods should not be called!')

    @property
    def resources(self):
      raise AssertionError('Non-JvmTarget resources query methods should not be called!')

  def test_find_all_relevant_resources_targets(self):
    resources1 = self.make_target('resources:target1', target_type=Resources)
    resources2 = self.make_target('resources:target2', target_type=Resources)
    resources3 = self.make_target('resources:target3', target_type=Resources)
    resources4 = self.make_target('resources:target4', target_type=Resources)
    jvm_target = self.make_target('jvm:target',
                                  target_type=JvmTarget,
                                  resources=[resources1.address.spec])
    java_library = self.make_target('java:target', target_type=JavaLibrary, sources=[])
    java_library2 = self.make_target('java:target2',
                                     target_type=JavaLibrary,
                                     sources=[],
                                     resources=[resources4.address.spec])
    other_target = self.make_target('other:target',
                                    target_type=self.NonJvmResourcesUsingTarget,
                                    resources=[resources3.address.spec])

    task = self.create_task(self.context(target_roots=[resources2,
                                                       jvm_target,
                                                       java_library,
                                                       java_library2,
                                                       other_target]))
    relevant_resources_targets = task.find_all_relevant_resources_targets()
    self.assertEqual(sorted([self.target('resources:target1'), self.target('resources:target4')]),
                     sorted(relevant_resources_targets))

  def test_find_all_relevant_resources_targets_transitive(self):
    # Insert a target alias between the resources and the jvm target.
    resources_target = self.make_target('resources:target', target_type=Resources)
    alias_target = self.make_target('alias:target',
                                    target_type=Target,
                                    dependencies=[resources_target])
    jvm_target = self.make_target('jvm:target',
                                  target_type=JvmTarget,
                                  dependencies=[alias_target])

    task = self.create_task(self.context(target_roots=[jvm_target]))
    relevant_resources_targets = task.find_all_relevant_resources_targets()
    self.assertEqual(sorted([resources_target]), sorted(relevant_resources_targets))

  def test_prepare_resources_none(self):
    task = self.create_task(self.context())
    resources = self.make_target('resources:target', target_type=Resources)
    with temporary_dir() as chroot:
      task.prepare_resources(resources, chroot)
      self.assertEqual([], os.listdir(chroot))

  def test_prepare_resources(self):
    task = self.create_task(self.context())
    self.create_file('resources/a/b.txt', 'a/b.txt')
    self.create_file('resources/c.txt', 'c.txt')
    resources = self.make_target('resources:target',
                                 target_type=Resources,
                                 sources=['a/b.txt', 'c.txt'])
    with temporary_dir() as chroot:
      task.prepare_resources(resources, chroot)
      resource_files = []
      for root, dirs, files in os.walk(chroot):
        for f in files:
          abs_path = os.path.join(root, f)
          rel_path = os.path.relpath(abs_path, chroot)
          with open(abs_path) as fp:
            self.assertEqual(rel_path, fp.read())
          resource_files.append(rel_path)
      self.assertEqual(sorted(['a/b.txt', 'c.txt']), sorted(resource_files))
