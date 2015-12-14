# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict

from pants.backend.jvm.subsystems.jvm_platform import JvmPlatformSettings
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import ZincCompile
from pants.base.revision import Revision
from pants.util.memo import memoized_method
from pants_test.tasks.task_test_base import TaskTestBase


class JavaCompileSettingsPartitioningTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return ZincCompile

  def _java(self, name, platform=None, deps=None, sources=None):
    return self.make_target(spec='java:{}'.format(name),
                            target_type=JavaLibrary,
                            platform=platform,
                            dependencies=deps or [],
                            sources=sources)

  def _platforms(self, *versions):
    return {str(v): {'source': str(v)} for v in versions}

  @memoized_method
  def _version(self, version):
    return Revision.lenient(version)

  def _task_setup(self, targets, platforms=None, default_platform=None, **options):
    options['source'] = options.get('source', '1.7')
    options['target'] = options.get('target', '1.7')
    self.set_options(**options)
    self.set_options_for_scope('jvm-platform', platforms=platforms,
                               default_platform=default_platform)
    context = self.context(target_roots=targets)
    return self.create_task(context)

  def _settings_and_targets(self, targets, **options):
    self._task_setup(targets, **options)
    settings_and_targets = defaultdict(set)
    for target in targets:
      settings_and_targets[target.platform].add(target)
    return settings_and_targets.items()

  def _partition(self, targets, **options):
    self._task_setup(targets, **options)
    partition = defaultdict(set)
    for target in targets:
      partition[target.platform.target_level].add(target)
    return partition

  def _format_partition(self, partition):
    return '{{{}\n  }}'.format(','.join(
      '\n    {}: [{}]'.format(key, ', '.join(sorted(t.address.spec for t in value)))
      for key, value in sorted(partition.items())
    ))

  def assert_partitions_equal(self, expected, received):
    # Convert to normal dicts and remove empty values.
    expected = {key: set(val) for key, val in expected.items() if val}
    received = {key: set(val) for key, val in received.items() if val}
    self.assertEqual(expected, received, 'Partitions are different!\n  expected: {}\n  received: {}'
                                        .format(self._format_partition(expected),
                                                self._format_partition(received)))

  def test_single_target(self):
    java6 = self._java('six', '1.6')
    partition = self._partition([java6], platforms=self._platforms('1.6'))
    self.assertEqual(1, len(partition))
    self.assertEqual({java6}, set(partition[self._version('1.6')]))

  def test_independent_targets(self):
    java6 = self._java('six', '1.6')
    java7 = self._java('seven', '1.7')
    java8 = self._java('eight', '1.8')
    partition = self._partition([java6, java7, java8],
                                platforms=self._platforms('1.6', '1.7', '1.8'))
    expected = {self._version(java.payload.platform): {java}
                for java in (java6, java7, java8)}
    self.assertEqual(3, len(partition))
    self.assert_partitions_equal(expected, partition)

  def test_java_version_aliases(self):
    expected = {}
    for version in (6, 7, 8):
      expected[Revision.lenient('1.{}'.format(version))] = {
        self._java('j1{}'.format(version), '1.{}'.format(version)),
        self._java('j{}'.format(version), '{}'.format(version)),
      }
    partition = self._partition(list(reduce(set.union, expected.values(), set())),
                                platforms=self._platforms('6', '7', '8', '1.6', '1.7', '1.8'))
    self.assertEqual(len(expected), len(partition))
    self.assert_partitions_equal(expected, partition)

  def test_valid_dependent_targets(self):
    java6 = self._java('six', '1.6')
    java7 = self._java('seven', '1.7')
    java8 = self._java('eight', '1.8', deps=[java6])

    partition = self._partition([java6, java7, java8],
                                platforms=self._platforms('1.6', '1.7', '1.8'))
    self.assert_partitions_equal({
      self._version('1.6'): {java6},
      self._version('1.7'): {java7},
      self._version('1.8'): {java8},
    }, partition)

  def test_unspecified_default(self):
    java = self._java('unspecified', None)
    java6 = self._java('six', '1.6', deps=[java])
    java7 = self._java('seven', '1.7', deps=[java])
    partition = self._partition([java7, java, java6], source='1.6', target='1.6',
                                platforms=self._platforms('1.6', '1.7'),
                                default_platform='1.6')
    self.assert_partitions_equal({
      self._version('1.6'): {java, java6},
      self._version('1.7'): {java7},
    }, partition)

  def test_invalid_source_target_combination_by_jvm_platform(self):
    java_wrong = self._java('source7target6', 'bad')
    with self.assertRaises(JvmPlatformSettings.IllegalSourceTargetCombination):
      self._settings_and_targets([java_wrong], platforms={
        'bad': {'source': '1.7', 'target': '1.6'}
      })

  def test_valid_source_target_combination(self):
    platforms = {
      'java67': {'source': 6, 'target': 7},
      'java78': {'source': 7, 'target': 8},
      'java68': {'source': 6, 'target': 8},
    }
    self._settings_and_targets([
      self._java('java67', 'java67'),
      self._java('java78', 'java78'),
      self._java('java68', 'java68'),
    ], platforms=platforms)

  def test_compile_setting_equivalence(self):
    self.assertEqual(JvmPlatformSettings('1.6', '1.6', ['-Xfoo:bar']),
                     JvmPlatformSettings('1.6', '1.6', ['-Xfoo:bar']))

  def test_compile_setting_inequivalence(self):
    self.assertNotEqual(JvmPlatformSettings('1.6', '1.6', ['-Xfoo:bar']),
                        JvmPlatformSettings('1.6', '1.7', ['-Xfoo:bar']))

    self.assertNotEqual(JvmPlatformSettings('1.6', '1.6', ['-Xfoo:bar']),
                        JvmPlatformSettings('1.6', '1.6', ['-Xbar:foo']))

    self.assertNotEqual(JvmPlatformSettings('1.4', '1.6', ['-Xfoo:bar']),
                        JvmPlatformSettings('1.6', '1.6', ['-Xfoo:bar']))
