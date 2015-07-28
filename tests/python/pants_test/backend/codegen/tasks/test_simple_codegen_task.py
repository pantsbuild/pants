# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.backend.codegen.register import build_file_aliases as register_codegen
from pants.backend.codegen.tasks.simple_codegen_task import SimpleCodegenTask
from pants.backend.core.register import build_file_aliases as register_core
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.exceptions import TaskError
from pants_test.tasks.task_test_base import TaskTestBase


class SimpleCodegenTaskTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return cls.DummyGen

  @property
  def alias_groups(self):
    return register_core().merge(register_codegen()).merge(BuildFileAliases.create({
      'dummy_library': SimpleCodegenTaskTest.DummyLibrary
    }))

  def _create_dummy_task(self, target_roots=None, forced_codegen_strategy=None,
                         hard_strategy_force=False, **options):
    self.set_options(**options)
    task = self.create_task(self.context(target_roots=target_roots))
    task.setup_for_testing(self, target_roots or [], forced_codegen_strategy, hard_strategy_force)
    return task

  def _create_dummy_library_targets(self, target_specs):
    for spec in target_specs:
      spec_path, spec_name = spec.split(':')
      self.add_to_build_file(spec_path, dedent('''
          dummy_library(name='{name}',
            sources=[],
          )
        '''.format(name=spec_name)))
    return set([self.target(spec) for spec in target_specs])

  def test_codegen_strategy(self):
    self.set_options(strategy='global')
    task = self.create_task(self.context())
    self.assertEqual('global', task.get_options().strategy)
    self.assertEqual('global', task.codegen_strategy.name())

    self.set_options(strategy='isolated')
    task = self.create_task(self.context())
    self.assertEqual('isolated', task.codegen_strategy.name())

    task = self._create_dummy_task(strategy='global', forced_codegen_strategy='global')
    self.assertEqual('global', task.codegen_strategy.name())
    task = self._create_dummy_task(strategy='isolated', forced_codegen_strategy='global')
    self.assertEqual('global', task.codegen_strategy.name())

  def test_codegen_workdir_suffix(self):
    targets = self._create_dummy_library_targets([
      'project/src/main/foogen/foo-lib:foo-target-a',
      'project/src/main/foogen/foo-lib:foo-target-b',
      'project/src/main/foogen/foo-bar:foo-target-a',
      'project/src/main/genfoo/foo-bar:foo-target-a',
    ])

    task = self.create_task(self.context())

    def get_suffix(target, strategy):
      return task._codegen_strategy_for_name(strategy).codegen_workdir_suffix(target)

    for target in targets:
      self.assertEqual('global', get_suffix(target, 'global'))
      self.assertTrue('isolated' in get_suffix(target, 'isolated'))

    global_dirs = set(get_suffix(target, 'global') for target in targets)
    isolated_dirs = set(get_suffix(target, 'isolated') for target in targets)

    self.assertEqual(1, len(global_dirs), 'There should only be one global directory suffix!')
    self.assertEqual(len(targets), len(isolated_dirs),
                     'There should be exactly one directory suffix per unique target!')

  def test_codegen_workdir_suffix_stability(self):
    specs = ['project/src/main/foogen/foo-lib:foo-target-a']
    for target in self._create_dummy_library_targets(specs):
      for strategy in (SimpleCodegenTask.IsolatedCodegenStrategy(None),
                       SimpleCodegenTaskTest.DummyGen.DummyGlobalStrategy(None)):
        self.assertEqual(strategy.codegen_workdir_suffix(target),
                         strategy.codegen_workdir_suffix(target),
                         'Codegen workdir suffix should be stable given the same target!\n'
                         '  target: {}'.format(target.address.spec))

  def _test_execute_strategy(self, strategy, expected_execution_count):
    dummy_suffixes = ['a', 'b', 'c',]

    self.add_to_build_file('gen-lib', '\n'.join(dedent('''
      dummy_library(name='{suffix}',
        sources=['org/pantsbuild/example/foo{suffix}.dummy'],
      )
    ''').format(suffix=suffix) for suffix in dummy_suffixes))

    for suffix in dummy_suffixes:
      self.create_file('gen-lib/org/pantsbuild/example/foo{suffix}.dummy'.format(suffix=suffix),
                       'org.pantsbuild.example Foo{0}'.format(suffix))

    targets = [self.target('gen-lib:{suffix}'.format(suffix=suffix)) for suffix in dummy_suffixes]
    task = self._create_dummy_task(target_roots=targets, strategy=strategy)
    expected_targets = set(targets)
    found_targets = set(task.codegen_targets())
    self.assertEqual(expected_targets, found_targets,
                     'TestGen failed to find codegen target {expected}! Found: [{found}].'
                     .format(expected=', '.join(t.id for t in expected_targets),
                             found=', '.join(t.id for t in found_targets)))
    task.execute()
    self.assertEqual(expected_execution_count, task.execution_counts,
                     '{} strategy had the wrong number of executions!\n  expected: {}\n  got: {}'
                     .format(strategy, expected_execution_count, task.execution_counts))

  def test_execute_global(self):
    self._test_execute_strategy('global', 1)

  def test_execute_isolated(self):
    self._test_execute_strategy('isolated', 3)

  def test_execute_fail(self):
    # Ensure whichever strategy is selected, it actually call execute_codegen to trigger our
    # DummyTask `should_fail` logic.  The isolated strategy, for example, short circuits that call
    # if there are no targets.
    dummy = self.make_target(spec='dummy', target_type=self.DummyLibrary)
    task = self._create_dummy_task(target_roots=[dummy])
    task.should_fail = True
    self.assertRaisesRegexp(TaskError, r'Failed to generate target\(s\)', task.execute)

  def _get_duplication_test_targets(self):
    self.add_to_build_file('gen-parent', dedent('''
      dummy_library(name='gen-parent',
        sources=['org/pantsbuild/example/parent.dummy'],
      )
    '''))

    self.add_to_build_file('gen-child', dedent('''
      dummy_library(name='good',
        sources=['org/pantsbuild/example/good-child.dummy'],
        dependencies=['gen-parent'],
      )

      dummy_library(name='bad',
        sources=['org/pantsbuild/example/bad-child.dummy'],
        dependencies=['gen-parent'],
      )
    '''))

    self.create_file('gen-parent/org/pantsbuild/example/parent.dummy',
                     'org.pantsbuild.example ParentClass')

    self.create_file('gen-child/org/pantsbuild/example/good-child.dummy',
                     'org.pantsbuild.example ChildClass')

    self.create_file('gen-child/org/pantsbuild/example/bad-child.dummy',
                     'org.pantsbuild.example ParentClass\n'
                     'org.pantsbuild.example ChildClass')

    return self.target('gen-parent'), self.target('gen-child:good'), self.target('gen-child:bad')

  def test_duplicated_code_generation(self):
    targets = self._get_duplication_test_targets()
    parent, good, bad = targets
    task = self._create_dummy_task(target_roots=targets, strategy='isolated', allow_dups=False)
    for target in targets:
      task.execute_codegen([target,])

    task = self._create_dummy_task(target_roots=targets, strategy='isolated', allow_dups=False)
    with self.assertRaises(SimpleCodegenTask.IsolatedCodegenStrategy.DuplicateSourceError) as cm:
      task.codegen_strategy.find_sources(bad)
    should_contain = ['org/pantsbuild/example/ParentClass']
    should_not_contain = ['org/pantsbuild/example/ChildClass']
    message = str(cm.exception)
    for item in should_contain:
      self.assertTrue(item in message, 'Error message should contain "{}".'.format(item))
    for item in should_not_contain:
      self.assertFalse(item in message, 'Error message should not contain "{}".'.format(item))

    # Should error same as above. Just to make sure the flag exists when the codegen strategy
    # is forced.
    task = self._create_dummy_task(target_roots=targets, strategy='isolated', allow_dups=False,
                                   forced_codegen_strategy='isolated')
    with self.assertRaises(SimpleCodegenTask.IsolatedCodegenStrategy.DuplicateSourceError):
      task.codegen_strategy.find_sources(bad)

    task = self._create_dummy_task(target_roots=targets, strategy='isolated', allow_dups=True)
    task.codegen_strategy.find_sources(bad) # Should not raise error, only warning.

    task = self._create_dummy_task(target_roots=targets, strategy='isolated', allow_dups=False)
    task.codegen_strategy.find_sources(good) # Should be completely fine.

  def test_unsupported_strategy_error(self):
    task = self._create_dummy_task(target_roots=[], forced_codegen_strategy='potato',
                                   hard_strategy_force=True)
    with self.assertRaises(SimpleCodegenTask.UnsupportedStrategyError):
      task.codegen_strategy

  class DummyLibrary(JvmTarget):
    """Library of .dummy files, which are just text files which generate empty java files.

    As the name implies, this is purely for testing the behavior of the simple_codegen_task.

    For example, a .dummy file with the contents:
    org.company.package Main
    org.company.package Foobar
    org.company.other Barfoo

    Would generate the files:
    org/company/package/Main.java,
    org/company/package/Foobar.java,
    org/company/other/Barfoo.java,

    Which would compile, but do nothing.
    """

  class DummyGen(SimpleCodegenTask):
    """Task which generates .java files for DummyLibraries.

    In addition to fulfilling the bare-minimum requirements of being a SimpleCodegenTask subclass,
    the methods in this class perform some validation to ensure that they are being called correctly
    by SimpleCodegenTask.
    """
    _forced_codegen_strategy = None
    _hard_forced_codegen_strategy = None

    def __init__(self, *vargs, **kwargs):
      super(SimpleCodegenTaskTest.DummyGen, self).__init__(*vargs, **kwargs)
      self._test_case = None
      self._all_targets = None
      self.setup_for_testing(None, None)
      self.should_fail = False
      self.execution_counts = 0

    def setup_for_testing(self, test_case, all_targets, forced_codegen_strategy=None,
                          hard_strategy_force=False):
      """Gets this dummy generator class ready for testing.

      :param TaskTestBase test_case: the 'parent' test-case using this task. Used for asserts, etc.
      :param set all_targets: the set of all valid code-gen targets for this task, for validating
        the correctness of the chosen strategy.
      :param str forced_codegen_strategy: the name of the forced codegen strategy ('isolated' or
        'global') is this task should force a particular strategy, or None if no strategy should be
        forced.
      :param bool hard_strategy_force: if true, absolutely forces the codegen strategy to be the
        of the given type, against all reason, even if it's unimplemented.
      """
      self._test_case = test_case
      self._all_targets = all_targets
      cls = type(self)
      cls._forced_codegen_strategy = forced_codegen_strategy
      cls._hard_forced_codegen_strategy = forced_codegen_strategy if hard_strategy_force else None

    @classmethod
    def forced_codegen_strategy(cls):
      if cls._hard_forced_codegen_strategy is None:
        return super(SimpleCodegenTaskTest.DummyGen, cls).forced_codegen_strategy()
      return cls._hard_forced_codegen_strategy

    @classmethod
    def supported_strategy_types(cls):
      if cls._forced_codegen_strategy is None or cls._hard_forced_codegen_strategy:
        return [cls.IsolatedCodegenStrategy, cls.DummyGlobalStrategy,]
      elif cls._forced_codegen_strategy == 'global':
        return [cls.DummyGlobalStrategy,]
      elif cls._forced_codegen_strategy == 'isolated':
        return [cls.IsolatedCodegenStrategy,]
      raise ValueError('Unrecognized _forced_codegen_strategy for test ({}).'
                       .format(cls._forced_codegen_strategy))

    def is_gentarget(self, target):
      return isinstance(target, SimpleCodegenTaskTest.DummyLibrary)

    def execute_codegen(self, invalid_targets):
      self.execution_counts += 1
      if self.should_fail: raise TaskError('Failed to generate target(s)')
      if self.codegen_strategy.name() == 'isolated':
        self._test_case.assertEqual(1, len(invalid_targets),
                                    'Codegen should execute individually in isolated mode.')
      elif self.codegen_strategy.name() == 'global':
        self._test_case.assertEqual(len(self._all_targets), len(invalid_targets),
                                    'Codegen should execute all together in global mode.'
                                    '\n all_targets={0}\n gen_targets={1}\n targets: '
                                    .format(len(self._all_targets), len(invalid_targets),
                                            ', '.join(t.address.spec for t in invalid_targets)))
      else:
        raise ValueError('Unknown codegen strategy "{}".'.format(self.codegen_strategy.name()))

      for target in invalid_targets:
        for path in self._dummy_sources_to_generate(target):
          class_name = os.path.basename(path).split('.')[0]
          package_name = os.path.relpath(os.path.dirname(path),
                                         self.codegen_workdir(target)).replace(os.path.sep, '.')
          if not os.path.exists(os.path.join(self._test_case.build_root, os.path.basename(path))):
            self._test_case.create_dir(os.path.basename(path))
          self._test_case.create_file(path)
          with open(path, 'w') as f:
            f.write('package {0};\n\n'.format(package_name))
            f.write('public class {0} '.format(class_name))
            f.write('{\n\\\\ ... nothing ... \n}\n')

    def sources_generated_by_target(self, target):
      self._test_case.assertEqual('global', self.codegen_strategy.name(),
                            'sources_generated_by_target should only be called for '
                            'strategy=global.')
      return self._dummy_sources_to_generate(target)

    def _dummy_sources_to_generate(self, target):
      for source in target.sources_relative_to_buildroot():
        source = os.path.join(self._test_case.build_root, source)
        with open(source, 'r') as f:
          for line in f:
            line = line.strip()
            if line:
              package_name, class_name = line.split(' ')
              yield os.path.join(self.codegen_workdir(target),
                                 os.path.join(*package_name.split('.')),
                                 class_name)

    def _find_sources_generated_by_target(self, target):
      self._test_case.assertEqual('isolated', self.codegen_strategy.name(),
                            '_find_sources_generated_by_target should only be called for '
                            'strategy=isolated.')
      return super(SimpleCodegenTaskTest.DummyGen, self)._find_sources_generated_by_target(target)

    @property
    def synthetic_target_type(self):
      return JavaLibrary

    class DummyGlobalStrategy(SimpleCodegenTask.GlobalCodegenStrategy):
      def find_sources(self, target):
        return self._task.sources_generated_by_target(target)
