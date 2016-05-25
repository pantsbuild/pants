# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import defaultdict
from contextlib import contextmanager

from pants.backend.jvm.subsystems.jvm_platform import JvmPlatformSettings
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jvm_compile.zinc.zinc_compile import ZincCompile
from pants.base.revision import Revision
from pants.java.distribution.distribution import DistributionLocator
from pants.util.memo import memoized_method
from pants.util.osutil import get_os_name, normalize_os_name
from pants_test.java.distribution.test_distribution import EXE, distribution
from pants_test.subsystem.subsystem_util import subsystem_instance
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

  def test_java_home_extraction(self):
    _, source, _, target, foo, bar, composite, single = tuple(ZincCompile._get_zinc_arguments(
      JvmPlatformSettings('1.7', '1.7', [
        'foo', 'bar', 'foo:$JAVA_HOME/bar:$JAVA_HOME/foobar', '$JAVA_HOME',
      ])
    ))

    self.assertEquals('-C1.7', source)
    self.assertEquals('-C1.7', target)
    self.assertEquals('foo', foo)
    self.assertEquals('bar', bar)
    self.assertNotEqual('$JAVA_HOME', single)
    self.assertNotIn('$JAVA_HOME', composite)
    self.assertEquals('foo:{0}/bar:{0}/foobar'.format(single), composite)

  def test_java_home_extraction_empty(self):
    result = tuple(ZincCompile._get_zinc_arguments(
      JvmPlatformSettings('1.7', '1.7', [])
    ))
    self.assertEquals(4, len(result),
                      msg='_get_zinc_arguments did not correctly handle empty args.')

  def test_java_home_extraction_missing_distributions(self):
    # This will need to be bumped if java ever gets to major version one million.
    far_future_version = '999999.1'
    farer_future_version = '999999.2'

    os_name = normalize_os_name(get_os_name())

    @contextmanager
    def fake_distributions(versions):
      """Create a fake JDK for each java version in the input, and yield the list of java_homes.

      :param list versions: List of java version strings.
      """
      fakes = []
      for version in versions:
        fakes.append(distribution(
          executables=[EXE('bin/java', version), EXE('bin/javac', version)],
        ))
      yield [d.__enter__() for d in fakes]
      for d in fakes:
        d.__exit__(None, None, None)

    @contextmanager
    def fake_distribution_locator(*versions):
      """Sets up a fake distribution locator with fake distributions.

      Creates one distribution for each java version passed as an argument, and yields a list of
      paths to the java homes for each distribution.
      """
      with fake_distributions(versions) as paths:
        path_options = {
          'jvm-distributions': {
            'paths': {
              os_name: paths,
            }
          }
        }
        with subsystem_instance(DistributionLocator, **path_options) as locator:
          yield paths
          locator._reset()

    # Completely missing a usable distribution.
    with fake_distribution_locator(far_future_version):
      with self.assertRaises(DistributionLocator.Error):
        ZincCompile._get_zinc_arguments(JvmPlatformSettings(
          source_level=farer_future_version,
          target_level=farer_future_version,
          args=['$JAVA_HOME/foo'],
        ))

    # Missing a strict distribution.
    with fake_distribution_locator(farer_future_version) as paths:
      results = ZincCompile._get_zinc_arguments(JvmPlatformSettings(
        source_level=far_future_version,
        target_level=far_future_version,
        args=['$JAVA_HOME/foo', '$JAVA_HOME'],
      ))
      self.assertEquals(paths[0], results[-1])
      self.assertEquals('{}/foo'.format(paths[0]), results[-2])

    # Make sure we pick up the strictest possible distribution.
    with fake_distribution_locator(farer_future_version, far_future_version) as paths:
      farer_path, far_path = paths
      results = ZincCompile._get_zinc_arguments(JvmPlatformSettings(
        source_level=far_future_version,
        target_level=far_future_version,
        args=['$JAVA_HOME/foo', '$JAVA_HOME'],
      ))
      self.assertEquals(far_path, results[-1])
      self.assertEquals('{}/foo'.format(far_path), results[-2])

    # Make sure we pick the higher distribution when the lower one doesn't work.
    with fake_distribution_locator(farer_future_version, far_future_version) as paths:
      farer_path, far_path = paths
      results = ZincCompile._get_zinc_arguments(JvmPlatformSettings(
        source_level=farer_future_version,
        target_level=farer_future_version,
        args=['$JAVA_HOME/foo', '$JAVA_HOME'],
      ))
      self.assertEquals(farer_path, results[-1])
      self.assertEquals('{}/foo'.format(farer_path), results[-2])
