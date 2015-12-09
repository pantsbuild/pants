# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.jvm_platform_analysis import JvmPlatformExplain, JvmPlatformValidate
from pants.build_graph.target import Target
from pants_test.tasks.task_test_base import TaskTestBase


class JvmPlatformAnalysisTestMixin(object):
  """Common helper methods for testing JvmPlatformValidate and JvmPlatformExplain.

  Mostly for building sets of targets that are interesting for testing.
  """

  def _java(self, name, platform=None, deps=None, sources=None):
    return self.make_target(spec='java:{}'.format(name),
                            target_type=JavaLibrary,
                            platform=platform,
                            dependencies=deps or [],
                            sources=sources)

  def _plain(self, name, deps=None):
    """Make a non-jvm target, useful for testing non-jvm intermediate dependencies."""
    return self.make_target(spec='java:{}'.format(name),
                            target_type=Target,
                            dependencies=deps or [],)

  def simple_task(self, targets, **options):
    self.set_options(**options)
    platforms = {
      '6': { 'source': 6, 'target': 6, 'args': [], },
      '7': { 'source': 7, 'target': 7, 'args': [], },
      '8': { 'source': 8, 'target': 8, 'args': [], },
    }
    self.set_options_for_scope('jvm-platform', platforms=platforms, default_platform='6')
    context = self.context(target_roots=targets)
    return self.create_task(context)

  def bad_targets(self):
    one = self._java('one', '7')
    two = self._java('two', '6', deps=[one])
    return [one, two]

  def good_targets(self):
    one = self._java('one', '6')
    two = self._java('two', '7', deps=[one])
    return [one, two]

  def bad_transitive_targets(self):
    one = self._java('one', '7')
    middle = self._plain('middle', deps=[one])
    two = self._java('two', '6', deps=[middle])
    return [one, two, middle]

  def good_transitive_targets(self):
    one = self._java('one', '6')
    middle = self._plain('middle', deps=[one])
    two = self._java('two', '7', deps=[middle])
    return [one, two, middle]

  def impossible_targets(self):
    a = self._java('a', '8')
    b = self._java('b', '7', deps=[a])
    c = self._java('c', '6', deps=[b])
    # :b depends on :a, which means :b can't have a target lower than 8.
    # :b is depended on by :c, which means :b can't have a target level higher than 6.
    return [a, b, c]


class JvmPlatformValidateTest(JvmPlatformAnalysisTestMixin, TaskTestBase):

  @classmethod
  def task_type(cls):
    return JvmPlatformValidate

  def assert_no_warning(self, targets, **options):
    self.assertTrue(self.simple_task(targets, **options).execute() is None)

  def assert_warning(self, targets, **options):
    self.assertTrue(self.simple_task(targets, **options).execute() is not None)

  def test_good_works(self):
    self.assert_no_warning(self.good_targets(), check='fatal')

  def test_transitive_good_works(self):
    self.assert_no_warning(self.good_transitive_targets(), check='fatal')

  def test_bad_fails(self):
    with self.assertRaises(JvmPlatformValidate.IllegalJavaTargetLevelDependency):
      self.simple_task(self.bad_targets(), check='fatal').execute()

  def test_transitive_bad_fails(self):
    with self.assertRaises(JvmPlatformValidate.IllegalJavaTargetLevelDependency):
      self.simple_task(self.bad_transitive_targets(), check='fatal').execute()

  def test_impossible_fails(self):
    with self.assertRaises(JvmPlatformValidate.IllegalJavaTargetLevelDependency):
      self.simple_task(self.impossible_targets(), check='fatal').execute()

  def test_bad_ignored(self):
    self.assert_no_warning(self.bad_targets(), check='off')

  def test_transitive_bad_ignored(self):
    self.assert_no_warning(self.bad_transitive_targets(), check='off')

  def test_bad_warned(self):
    self.assert_warning(self.bad_targets(), check='warn')

  def test_transitive_bad_warned(self):
    self.assert_warning(self.bad_transitive_targets(), check='warn')

  def test_inverted_ordering_works(self):
    self.assert_warning(self.bad_targets(), check='warn', children_before_parents=True)

  def construct_interesting_graph(self):
    """Constructs an "interesting" transitive graph, with a mix of jvm and non-jvm targets.

    Drawn in ascii below, with '->' indicating dependencies, with capital letters indicating
    JvmTargets and lower-case letters indicating non-JvmTargets.

    A -> B
      -> c -> D -> l -> N
           -> f -> G
           -> e -> q

    Constructed to demonstrate the behavior of jvm_dependency_map on dependency
    graphs that include many intermediate dependencies which are not JvmTargets.
    """
    q = self._plain('q')
    e = self._plain('e', deps=[q])
    n = self._java('n')
    l = self._plain('l', deps=[n])
    d = self._java('d', deps=[l])
    g = self._java('g')
    f = self._plain('f', deps=[g])
    c = self._plain('c', deps=[d,f,e])
    b = self._java('b')
    a = self._java('a', deps=[b,c])
    return [a,b,c,d,e,f,g,q,n,l]

  def assert_depmaps_equal(self, expected, received):
    jvm_deps = {target.name: ''.join(sorted({t.name for t in deps}))
                for target, deps in received.items()}
    for target, deps in sorted(expected.items()):
      got = jvm_deps.get(target, ())
      self.assertEqual(set(deps), set(got), '{}\n  expected {}\n  got {}\n  \n{}'
                       .format(target, deps, got, '\n'.join(
        '{}: {}'.format(key, val) for key, val in sorted(jvm_deps.items())
      )))
    self.assertEqual(len(filter(expected.get, expected)), len(filter(jvm_deps.get, jvm_deps)))

  def test_non_jvm_transitivity(self):
    """Tests the behavior of jvm_dependency_map."""
    expected = {
      'n': '',
      'g': '',
      'q': '',
      'l': 'n',
      'd': 'n',
      'f': 'g',
      'e': '',
      'c': 'gd',
      'b': '',
      'a': 'gdb',
    }
    jvm_deps = self.simple_task(self.construct_interesting_graph())._unfiltered_jvm_dependency_map()
    self.assert_depmaps_equal(expected, jvm_deps)

  def test_full_transitivity(self):
    """Tests the behavior of jvm_dependency_map when including all transitive dependencies."""
    expected = {
      'n': '',
      'g': '',
      'q': '',
      'l': 'n',
      'd': 'n',
      'f': 'g',
      'e': '',
      'c': 'gdn',
      'b': '',
      'a': 'gdbn',
    }
    task = self.simple_task(self.construct_interesting_graph())
    jvm_deps = task._unfiltered_jvm_dependency_map(fully_transitive=True)
    self.assert_depmaps_equal(expected, jvm_deps)


class JvmPlatformExplainTest(JvmPlatformAnalysisTestMixin, TaskTestBase):

  @classmethod
  def task_type(cls):
    return JvmPlatformExplain

  def get_lines(self, targets, trimmed=True, **options):
    output = self.simple_task(targets, **options).console_output(targets)
    if trimmed:
      output = [line.strip() for line in output if line and line.strip()]
    return tuple(output)

  def assert_lines(self, lines, targets, **options):
    self.assertEqual(lines, self.get_lines(targets, **options))

  def assert_length(self, count, targets, **options):
    self.assertEqual(count, len(self.get_lines(targets, **options)))

  def test_change_only_quiet(self):
    lines = self.get_lines(self.good_targets(), only_broken=True)
    self.assertEqual(1, len(lines))
    self.assertIn('Allowable JVM platform ranges', lines[0])

  def test_undetailed_good(self):
    targets = self.good_transitive_targets()
    self.assert_length(len(targets), targets, detailed=False)

  def test_broken(self):
    one = self._java('one', '7')
    two = self._java('two', '6', deps=[one])
    targets = [one, two]
    expected = ('Allowable JVM platform ranges (* = anything):',
                'java:one: <=1.6  (is 1.7)',
                'max=1.6 because of dependees:',
                'java:two',
                'java:two: 1.7+  (is 1.6)',
                'min=1.7 because of dependencies:',
                'java:one',)
    self.assert_lines(expected, targets, only_broken=True, colors=False)

  def test_upgradeable(self):
    one = self._java('one', '6')
    two = self._java('two', '7', deps=[one])
    three = self._java('three', '6', deps=[one])
    text = '\n'.join(self.get_lines([one, two, three], colors=False, ranges=False, upgradeable=True))
    self.assertNotIn('java:one', text)
    self.assertIn('java:three', text)
    self.assertIn('java:two', text)

  def test_downgradeable(self):
    one = self._java('one', '6')
    two = self._java('two', '7', deps=[one])
    nope = self._java('nope', '6', deps=[one])
    text = '\n'.join(self.get_lines([one, two, nope], colors=False, ranges=False,
                                    downgradeable=True))
    self.assertIn('java:one', text)
    self.assertNotIn('java:nope', text)
    self.assertIn('java:two', text)
