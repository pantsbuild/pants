# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.base.payload import Payload
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.build_graph.register import build_file_aliases as register_core
from pants.build_graph.target import Target
from pants.invalidation.build_invalidator import CacheKey
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.dirutil import safe_mkdtemp
from pants_test.tasks.task_test_base import TaskTestBase, ensure_cached


# A dummy target with sources= and copied= fields.
class DummyTargetBase(Target):
  def __init__(self, address, sources, copied=None, **kwargs):
    self.copied = copied
    payload = Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources, address.spec_path, key_arg='sources'),
    })
    super(DummyTargetBase, self).__init__(address=address, payload=payload, **kwargs)


class SyntheticDummyLibrary(DummyTargetBase):
  pass


class DummyLibrary(DummyTargetBase):
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
  pass


class DummyGen(SimpleCodegenTask):
  """Task which generates .java files for DummyLibraries.

  In addition to fulfilling the bare-minimum requirements of being a SimpleCodegenTask subclass,
  the methods in this class perform some validation to ensure that they are being called correctly
  by SimpleCodegenTask.
  """

  def __init__(self, *args, **kwargs):
    super(DummyGen, self).__init__(*args, **kwargs)
    self._test_case = None
    self.setup_for_testing(None)
    self.execution_counts = 0

  def setup_for_testing(self, test_case):
    """Gets this dummy generator class ready for testing.

    :param TaskTestBase test_case: the 'parent' test-case using this task. Used for asserts, etc.
    """
    self._test_case = test_case

  def is_gentarget(self, target):
    return isinstance(target, DummyLibrary)

  def execute_codegen(self, target, target_workdir):
    self.execution_counts += 1

    for path in self._dummy_sources_to_generate(target, target_workdir):
      class_name = os.path.basename(path).split('.')[0]
      package_name = os.path.relpath(os.path.dirname(path),
                                      target_workdir).replace(os.path.sep, '.')
      if not os.path.exists(os.path.join(self._test_case.build_root, os.path.basename(path))):
        self._test_case.create_dir(os.path.basename(path))
      self._test_case.create_file(path)
      with open(path, 'w') as f:
        f.write('package {0};\n\n'.format(package_name))
        f.write('public class {0} '.format(class_name))
        f.write('{\n\\\\ ... nothing ... \n}\n')

  def _dummy_sources_to_generate(self, target, target_workdir):
    for source in target.sources_relative_to_buildroot():
      source = os.path.join(self._test_case.build_root, source)
      with open(source, 'r') as f:
        for line in f:
          line = line.strip()
          if line:
            package_name, class_name = line.split(' ')
            yield os.path.join(target_workdir, os.path.join(*package_name.split('.')), class_name)

  def synthetic_target_type(self, target):
    return SyntheticDummyLibrary

  @property
  def _copy_target_attributes(self):
    return ['copied']


class SimpleCodegenTaskTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return DummyGen

  @property
  def alias_groups(self):
    return register_core().merge(BuildFileAliases({
      'dummy_library': DummyLibrary
    }))

  def _create_dummy_task(self, target_roots=None, **options):
    self.set_options(**options)
    task = self.create_task(self.context(target_roots=target_roots))
    task.setup_for_testing(self)
    return task

  def _create_dummy_library_targets(self, target_specs):
    for spec in target_specs:
      spec_path, spec_name = spec.split(':')
      self.add_to_build_file(spec_path, dedent("""
          dummy_library(name='{name}',
            sources=[],
          )
        """.format(name=spec_name)))
    return set([self.target(spec) for spec in target_specs])

  @ensure_cached(DummyGen)
  def test_expected_codegen_targets_and_right_execution_count(self):
    expected_execution_count = 3
    dummy_suffixes = ['a', 'b', 'c']

    self.add_to_build_file('gen-lib', '\n'.join(dedent("""
        dummy_library(name='{suffix}',
          sources=['org/pantsbuild/example/foo{suffix}.dummy'],
        )
      """).format(suffix=suffix) for suffix in dummy_suffixes))

    for suffix in dummy_suffixes:
      self.create_file('gen-lib/org/pantsbuild/example/foo{suffix}.dummy'.format(suffix=suffix),
        'org.pantsbuild.example Foo{0}'.format(suffix))

    targets = [self.target('gen-lib:{suffix}'.format(suffix=suffix)) for suffix in dummy_suffixes]
    task = self._create_dummy_task(target_roots=targets)

    expected_targets = set(targets)
    found_targets = set(task.codegen_targets())
    self.assertEqual(expected_targets, found_targets,
      'TestGen failed to find codegen target {expected}! Found: [{found}].'
        .format(expected=', '.join(t.id for t in expected_targets),
        found=', '.join(t.id for t in found_targets)))

    task.execute()

    self.assertEqual(expected_execution_count, task.execution_counts,
      'had the wrong number of executions!\n  expected: {}\n  got: {}'
        .format(expected_execution_count, task.execution_counts))

  def _get_duplication_test_targets(self):
    self.add_to_build_file('gen-parent', dedent("""
      dummy_library(name='gen-parent',
        sources=['org/pantsbuild/example/parent.dummy'],
      )
    """))

    self.add_to_build_file('gen-child', dedent("""
      dummy_library(name='good',
        sources=['org/pantsbuild/example/good-child.dummy'],
        dependencies=['gen-parent'],
      )

      dummy_library(name='bad',
        sources=['org/pantsbuild/example/bad-child.dummy'],
        dependencies=['gen-parent'],
      )
    """))

    self.create_file('gen-parent/org/pantsbuild/example/parent.dummy',
                     'org.pantsbuild.example ParentClass')

    self.create_file('gen-child/org/pantsbuild/example/good-child.dummy',
                     'org.pantsbuild.example ChildClass')

    self.create_file('gen-child/org/pantsbuild/example/bad-child.dummy',
                     'org.pantsbuild.example ParentClass\n'
                     'org.pantsbuild.example ChildClass')

    return self.target('gen-parent'), self.target('gen-child:good'), self.target('gen-child:bad')

  def _do_test_duplication(self, targets, allow_dups, should_fail):
    task = self._create_dummy_task(target_roots=targets, allow_dups=allow_dups)
    target_workdirs = {t: safe_mkdtemp(dir=task.workdir) for t in targets}
    syn_targets = []

    # Generate and inject code for each target.
    def execute():
      for target in targets:
        target_workdir = target_workdirs[target]
        task.execute_codegen(target, target_workdir)
        task._handle_duplicate_sources(target, target_workdir)
        fingerprint = CacheKey("test", target.invalidation_hash())
        syn_targets.append(task._inject_synthetic_target(target, target_workdir, fingerprint))

    if should_fail:
      # If we're expected to fail, validate the resulting message.
      with self.assertRaises(SimpleCodegenTask.DuplicateSourceError) as cm:
        execute()
      should_contain = ['org/pantsbuild/example/ParentClass']
      should_not_contain = ['org/pantsbuild/example/ChildClass']
      message = str(cm.exception)
      for item in should_contain:
        self.assertTrue(item in message, 'Error message should contain "{}".'.format(item))
      for item in should_not_contain:
        self.assertFalse(item in message, 'Error message should not contain "{}".'.format(item))
    else:
      # Execute successfully.
      execute()

    return tuple(syn_targets)

  def test_duplicated_code_generation_fail(self):
    targets = self._get_duplication_test_targets()
    self._do_test_duplication(targets, allow_dups=False, should_fail=True)

  def test_duplicated_code_generation_pass(self):
    # Allow dupes.
    targets = self._get_duplication_test_targets()
    parent, good, bad = self._do_test_duplication(targets, allow_dups=True, should_fail=False)
    # Confirm that the duped sources were removed.
    for source in bad.sources_relative_to_source_root():
      self.assertNotIn(source, parent.sources_relative_to_source_root())

  def test_duplicated_code_generation_nodupes(self):
    # Without the duplicated target, either mode is fine.
    targets = self._get_duplication_test_targets()[:-1]
    self._do_test_duplication(targets, allow_dups=False, should_fail=False)
    self._do_test_duplication(targets, allow_dups=True, should_fail=False)

  def test_copy_target_attributes(self):
    self.create_file('fleem/org/pantsbuild/example/fleem.dummy',
                     'org.pantsbuild.example Fleem')


    self.add_to_build_file('fleem', dedent("""
      dummy_library(name='fleem',
        sources=['org/pantsbuild/example/fleem.dummy'],
        copied='copythis'
      )
    """))

    targets = [self.target('fleem')]
    task = self._create_dummy_task(target_roots=targets)
    task.execute()
    self.assertEqual('copythis', task.codegen_targets()[0].copied)

  def test_invalidation_of_generated_sources(self):
    self.create_file('src/thrift/com/foo/one.thrift', 'initial state')

    t1 = self.make_target(spec='src/thrift/com/foo:one',
                          target_type=DummyLibrary,
                          sources=['one.thrift'])

    task1 = self._create_dummy_task(target_roots=t1)
    task1.execute()

    gen_targets = [self.build_graph.get_target(syn_addr)
                   for syn_addr in self.build_graph.synthetic_addresses]
    syn_targets_for_t1 = [target for target in gen_targets if target.derived_from == t1]

    t1_hash = syn_targets_for_t1[0].invalidation_hash()

    self.reset_build_graph()

    self.create_file('src/thrift/com/foo/one.thrift', 'changed state')

    t2 = self.make_target(spec='src/thrift/com/foo:one',
                          target_type=DummyLibrary,
                          sources=['one.thrift'])

    task2 = self._create_dummy_task(target_roots=t2)
    task2.execute()

    gen_targets = [self.build_graph.get_target(syn_addr)
                   for syn_addr in self.build_graph.synthetic_addresses]
    syn_targets_for_t2 = [target for target in gen_targets if target.derived_from == t2]

    t2_hash = syn_targets_for_t2[0].invalidation_hash()
    self.assertNotEqual(t1_hash, t2_hash)


class ExportingDummyGen(DummyGen):

  def __init__(self, *args, **kwargs):
    super(ExportingDummyGen, self).__init__(*args, **kwargs)
    self.synthetic_type = ExportingSyntheticDummyLibrary
    self.synthetic_exports = ['marionette:no-strings']
    self.synthetic_dependencies = ['marionette:no-strings']

  def synthetic_target_extra_exports(self, target, target_workdir):
    return [self.context.build_graph.get_target_from_spec(s) for s in self.synthetic_exports]

  def synthetic_target_extra_dependencies(self, target, target_workdir):
    return [self.context.build_graph.get_target_from_spec(s) for s in self.synthetic_dependencies]

  def synthetic_target_type(self, target):
    return self.synthetic_type


class ExportingDummyLibrary(DummyLibrary):
  def __init__(self, exports=None, **kwargs):
    super(ExportingDummyLibrary, self).__init__(**kwargs)
    self._export_specs = exports or tuple() # NB: export_specs can't be None

  @property
  def export_specs(self):
    return self._export_specs


class ExportingSyntheticDummyLibrary(SyntheticDummyLibrary):
  def __init__(self, address, sources, exports=None, **kwargs):
    super(ExportingSyntheticDummyLibrary, self).__init__(address, sources, **kwargs)
    self._export_specs = exports or tuple() # NB: export_specs can't be None

  @property
  def export_specs(self):
    return self._export_specs


class ExportSimpleCodegenTaskTest(TaskTestBase):

  @classmethod
  def task_type(cls):
    return ExportingDummyGen

  @property
  def alias_groups(self):
    return register_core().merge(BuildFileAliases({
      'target': Target,
      'dummy_library': DummyLibrary,
      'exporting_dummy_library': ExportingDummyLibrary
    }))

  def _create_dummy_task(self,
    target_roots=None,
    synthetic_type=ExportingSyntheticDummyLibrary,
    synthetic_exports=None,
    synthetic_dependencies=None,
    **options):

    self.set_options(**options)
    task = self.create_task(self.context(target_roots=target_roots))
    task.synthetic_type = synthetic_type
    if synthetic_exports is not None:
      task.synthetic_exports = synthetic_exports
    if synthetic_dependencies is not None:
      task.synthetic_dependencies = synthetic_dependencies

    task.setup_for_testing(self)
    return task

  def synthetic_target_for(self, spec):
    for syn_addr in self.build_graph.synthetic_addresses:
      t = self.build_graph.get_target(syn_addr)
      if t.derived_from == self.build_graph.get_target_from_spec(spec):
        return t
    else:
      return None

  def test_add_export_from_target_that_supports_exports(self):
    self.add_to_build_file('marionette', dedent("""
      dummy_library(name='no-strings', sources=[])
    """))
    self.target('marionette:no-strings')

    self.create_file('fleem/org/pantsbuild/example/fleem.dummy',
      'org.pantsbuild.example Fleem')
    self.add_to_build_file('fleem', dedent("""
      exporting_dummy_library(name='fleem',
        sources=['org/pantsbuild/example/fleem.dummy'],
      )
    """))

    targets = [self.target('fleem')]
    task = self._create_dummy_task(target_roots=targets)
    task.execute()

    self.assertEqual(self.synthetic_target_for('fleem').export_specs, ['marionette:no-strings'])

  def test_skip_adding_export_from_target_that_supports_exports_to_one_that_doesnt(self):
    self.add_to_build_file('marionette', dedent("""
      dummy_library(name='no-strings', sources=[])
    """))
    self.target('marionette:no-strings')

    self.create_file('fleem/org/pantsbuild/example/fleem.dummy',
      'org.pantsbuild.example Fleem')
    self.add_to_build_file('fleem', dedent("""
      exporting_dummy_library(name='fleem',
        sources=['org/pantsbuild/example/fleem.dummy'],
      )
    """))

    targets = [self.target('fleem')]
    task = self._create_dummy_task(target_roots=targets, synthetic_type=SyntheticDummyLibrary)
    task.execute()

    self.assertEqual(type(self.synthetic_target_for('fleem')), SyntheticDummyLibrary)

  def test_merges_exports(self):
    self.add_to_build_file('marionette', dedent("""
      dummy_library(name='no-strings', sources=[])
    """))
    self.target('marionette:no-strings')

    self.create_file('fleem/org/pantsbuild/example/fleem.dummy',
      'org.pantsbuild.example Fleem')
    self.add_to_build_file('fleem', dedent("""
      dummy_library(name='flaam', sources=[])

      exporting_dummy_library(name='fleem',
        sources=['org/pantsbuild/example/fleem.dummy'],
        dependencies=[':flaam'],
        exports=[':flaam']
      )
    """))

    targets = [self.target('fleem')]
    task = self._create_dummy_task(target_roots=targets)
    task.execute()

    self.assertIn('fleem:flaam',self.synthetic_target_for('fleem').export_specs)
    self.assertIn('marionette:no-strings',self.synthetic_target_for('fleem').export_specs)

  def test_exports_always_copied_even_if_no_extra(self):
    self.add_to_build_file('marionette', dedent("""
      dummy_library(name='no-strings', sources=[])
    """))
    self.target('marionette:no-strings')

    self.create_file('fleem/org/pantsbuild/example/fleem.dummy',
      'org.pantsbuild.example Fleem')
    self.add_to_build_file('fleem', dedent("""
      dummy_library(name='flaam', sources=[])

      exporting_dummy_library(name='fleem',
        sources=['org/pantsbuild/example/fleem.dummy'],
        dependencies=[':flaam'],
        exports=[':flaam']
      )
    """))

    targets = [self.target('fleem')]
    task = self._create_dummy_task(target_roots=targets, synthetic_exports=[])

    task.execute()

    self.assertIn('fleem:flaam',self.synthetic_target_for('fleem').export_specs)

  def test_missing_extra_dependency_fails(self):
    self.add_to_build_file('marionette', dedent("""
      dummy_library(name='no-strings', sources=[])
    """))
    self.target('marionette:no-strings')

    self.create_file('fleem/org/pantsbuild/example/fleem.dummy',
      'org.pantsbuild.example Fleem')
    self.add_to_build_file('fleem', dedent("""
      dummy_library(name='flaam', sources=[])

      exporting_dummy_library(name='fleem',
        sources=['org/pantsbuild/example/fleem.dummy'],
      )
    """))

    targets = [self.target('fleem')]
    task = self._create_dummy_task(
      target_roots=targets,
      synthetic_exports=['marionette:no-strings'],
      synthetic_dependencies=[])

    with self.assertRaises(SimpleCodegenTask.MismatchedExtraExports):
      task.execute()

  def test_additional_extra_dependency_fine(self):
    self.add_to_build_file('marionette', dedent("""
      dummy_library(name='no-strings', sources=[])
    """))
    self.target('marionette:no-strings')

    self.create_file('fleem/org/pantsbuild/example/fleem.dummy',
      'org.pantsbuild.example Fleem')
    self.add_to_build_file('fleem', dedent("""
      dummy_library(name='flaam', sources=[])

      exporting_dummy_library(name='fleem',
        sources=['org/pantsbuild/example/fleem.dummy'],
      )
    """))

    targets = [self.target('fleem')]
    task = self._create_dummy_task(target_roots=targets,
      synthetic_exports=[],
      synthetic_dependencies=['marionette:no-strings'])

    task.execute()

    self.assertEqual(
      self.synthetic_target_for('fleem').dependencies[0].address.spec,
      'marionette:no-strings')
