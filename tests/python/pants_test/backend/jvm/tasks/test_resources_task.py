# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.jvm.tasks.resources_task import ResourcesTask
from pants.base.fingerprint_strategy import DefaultFingerprintStrategy
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField, stable_json_sha1
from pants.build_graph.target import Target
from pants.goal.products import UnionProducts
from pants.util.dirutil import touch
from pants_test.tasks.task_test_base import TaskTestBase


class ResourcesTaskTestBase(TaskTestBase):
  class TestTarget(Target):
    def __init__(self, contents, **kwargs):
      payload = Payload()
      payload.add_field('contents', PrimitiveField(contents))
      super(MinimalImplResourcesTaskTest.TestTarget, self).__init__(payload=payload, **kwargs)

  class MinimalImplResourcesTask(ResourcesTask):
    @staticmethod
    def get_target_ordinal(target):
      try:
        return int(target.name)
      except (TypeError, ValueError):
        return 0

    def find_all_relevant_resources_targets(self):
      def odd_targets(target):
        return self.get_target_ordinal(target) % 2 == 1
      return self.context.targets(predicate=odd_targets)

    def prepare_resources(self, target, chroot):
      for i in range(self.get_target_ordinal(target)):
        touch(os.path.join(chroot, target.id, str(i)))

  def create_resources_task(self, target_roots=None, **options):
    self.set_options(**options)
    context = self.context(target_roots=target_roots)
    context.products.safe_create_data('compile_classpath', init_func=UnionProducts)
    return self.create_task(context)

  def create_target(self, spec, contents=None, **kwargs):
    return self.make_target(spec, target_type=self.TestTarget, contents=contents, **kwargs)

  def assert_no_products(self, task, target):
    compile_classpath = task.context.products.get_data('compile_classpath')
    resources_by_target = task.context.products.get_data('resources_by_target')

    self.assertEqual(0, len(compile_classpath.get_for_target(target)))
    self.assertFalse(resources_by_target[target])

  def assert_products(self, task, target, count, expected_confs=None):
    compile_classpath = task.context.products.get_data('compile_classpath')
    resources_by_target = task.context.products.get_data('resources_by_target')

    expected_confs = expected_confs or ('default',)
    products = compile_classpath.get_for_target(target)
    self.assertEqual(len(expected_confs), len(products))

    confs = []
    chroots = set()
    for conf, chroot in products:
      confs.append(conf)
      chroots.add(chroot)
    self.assertEqual(sorted(expected_confs), sorted(confs))
    self.assertEqual(1, len(chroots))
    chroot = chroots.pop()

    resource_rel_paths = []
    for root, rel_paths in resources_by_target[target].rel_paths():
      self.assertEqual(chroot, root)
      resource_rel_paths.extend(rel_paths)

    classpath_rel_paths = []
    for root, dirs, files in os.walk(chroot):
      classpath_rel_paths.extend(os.path.relpath(os.path.join(root, f), chroot) for f in files)

    self.assertEqual(sorted(resource_rel_paths), sorted(classpath_rel_paths))
    self.assertEqual(sorted(os.path.join(target.id, str(i)) for i in range(count)),
                     sorted(resource_rel_paths))


class MinimalImplResourcesTaskTest(ResourcesTaskTestBase):
  @classmethod
  def task_type(cls):
    return cls.MinimalImplResourcesTask

  def test_no_resources_targets(self):
    task = self.create_resources_task(target_roots=[self.create_target('2'),
                                                    self.create_target('a')])
    processed_targets = task.execute()

    self.assertEqual([], processed_targets)
    self.assert_no_products(task, self.target('2'))
    self.assert_no_products(task, self.target('a'))

  def test_resources_targets(self):
    task = self.create_resources_task(target_roots=[self.create_target('a:1'),
                                                    self.create_target('a:2'),
                                                    self.create_target('a:3'),
                                                    self.create_target('b:1')])
    processed_targets = task.execute()

    self.assertEqual(sorted([self.target('a:1'), self.target('a:3'), self.target('b:1')]),
                     sorted(processed_targets))
    self.assert_products(task, self.target('a:1'), 1)
    self.assert_no_products(task, self.target('a:2'))
    self.assert_products(task, self.target('a:3'), 3)
    self.assert_products(task, self.target('b:1'), 1)

    # Test incremental works.
    self.reset_build_graph()
    task = self.create_resources_task(target_roots=[self.create_target('a:1'),
                                                    self.create_target('a:2'),
                                                    self.create_target('a:3'),
                                                    self.create_target('b:1')])
    processed_targets = task.execute()

    self.assertEqual([], processed_targets)
    self.assert_products(task, self.target('a:1'), 1)
    self.assert_no_products(task, self.target('a:2'))
    self.assert_products(task, self.target('a:3'), 3)
    self.assert_products(task, self.target('b:1'), 1)

  def test_incremental(self):
    task = self.create_resources_task(target_roots=[self.create_target('a:1'),
                                                    self.create_target('b:1')])
    processed_targets = task.execute()

    self.assertEqual(sorted([self.target('a:1'), self.target('b:1')]), sorted(processed_targets))
    self.assert_products(task, self.target('a:1'), 1)
    self.assert_products(task, self.target('b:1'), 1)

    # Test incremental works - no changes.
    self.reset_build_graph()
    task = self.create_resources_task(target_roots=[self.create_target('a:1'),
                                                    self.create_target('b:1')])
    processed_targets = task.execute()

    self.assertEqual([], processed_targets)
    self.assert_products(task, self.target('a:1'), 1)
    self.assert_products(task, self.target('b:1'), 1)

    # Test incremental works - a change in the default payload fingerprint.
    self.reset_build_graph()
    task = self.create_resources_task(target_roots=[self.create_target('a:1', contents='new'),
                                                    self.create_target('b:1')])
    processed_targets = task.execute()

    self.assertEqual([self.target('a:1')], processed_targets)
    self.assert_products(task, self.target('a:1'), 1)
    self.assert_products(task, self.target('b:1'), 1)

  def test_custom_confs(self):
    task = self.create_resources_task(target_roots=[self.create_target('a:1')], confs=('a', 'b'))
    processed_targets = task.execute()

    self.assertEqual([self.target('a:1')], processed_targets)
    self.assert_products(task, self.target('a:1'), 1, expected_confs=('a', 'b'))


class CustomInvalidationStrategtResourcesTaskTest(ResourcesTaskTestBase):
  class TagsInvalidationStrategy(DefaultFingerprintStrategy):
    def compute_fingerprint(self, target):
      return stable_json_sha1(sorted(target.tags))

  class CustomInvalidationStrategyResourcesTask(ResourcesTaskTestBase.MinimalImplResourcesTask):
    def create_invalidation_strategy(self):
      return CustomInvalidationStrategtResourcesTaskTest.TagsInvalidationStrategy()

  @classmethod
  def task_type(cls):
    return cls.CustomInvalidationStrategyResourcesTask

  def test_incremental(self):
    task = self.create_resources_task(target_roots=[self.create_target('a:1', tags=['plain']),
                                                    self.create_target('b:1')])
    processed_targets = task.execute()

    self.assertEqual(sorted([self.target('a:1'), self.target('b:1')]), sorted(processed_targets))
    self.assert_products(task, self.target('a:1'), 1)
    self.assert_products(task, self.target('b:1'), 1)

    # Test incremental works - no relevant changes.
    self.reset_build_graph()
    task = self.create_resources_task(target_roots=[self.create_target('a:1', tags=['plain']),
                                                    self.create_target('b:1', contents='bob')])
    processed_targets = task.execute()

    self.assertEqual([], processed_targets)
    self.assert_products(task, self.target('a:1'), 1)
    self.assert_products(task, self.target('b:1'), 1)

    # Test incremental works - a change in the custom fingerprint.
    self.reset_build_graph()
    task = self.create_resources_task(target_roots=[self.create_target('a:1', tags=['plain']),
                                                    self.create_target('b:1', tags='plain')])
    processed_targets = task.execute()

    self.assertEqual([self.target('b:1')], processed_targets)
    self.assert_products(task, self.target('a:1'), 1)
    self.assert_products(task, self.target('b:1'), 1)


class CustomRelativeResourcePathsResourcesTaskTest(ResourcesTaskTestBase):
  class CustomRelativeResourcePathsResourcesTask(ResourcesTaskTestBase.MinimalImplResourcesTask):
    def relative_resource_paths(self, target, chroot):
      return list(target.tags)

  @classmethod
  def task_type(cls):
    return cls.CustomRelativeResourcePathsResourcesTask

  def test_products(self):
    task = self.create_resources_task(target_roots=[self.create_target('a:1', tags=['red', 'blue']),
                                                    self.create_target('b:1')])
    processed_targets = task.execute()

    self.assertEqual(sorted([self.target('a:1'), self.target('b:1')]), sorted(processed_targets))

    compile_classpath = task.context.products.get_data('compile_classpath')
    resources_by_target = task.context.products.get_data('resources_by_target')

    # a:1 should generate products since it reports 2 tag-files.
    products = compile_classpath.get_for_target(self.target('a:1'))
    self.assertEqual(1, len(products))
    conf, chroot = products.pop()
    self.assertEqual('default', conf)

    resource_rel_paths = []
    for root, rel_paths in resources_by_target[self.target('a:1')].rel_paths():
      self.assertEqual(chroot, root)
      resource_rel_paths.extend(rel_paths)
    self.assertEqual(sorted(['red', 'blue']), sorted(resource_rel_paths))

    # b:1 should not generate products since it has no tag-files.
    products = compile_classpath.get_for_target(self.target('b:1'))
    self.assertEqual(0, len(products))
    self.assertFalse(resources_by_target[self.target('b:1')])
