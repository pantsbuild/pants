# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.files import Files
from pants.cache.cache_setup import CacheSetup
from pants.option.arg_splitter import GLOBAL_SCOPE
from pants.subsystem.subsystem import Subsystem
from pants.subsystem.subsystem_client_mixin import SubsystemDependency
from pants.task.task import Task
from pants.util.dirutil import safe_rmtree
from pants_test.tasks.task_test_base import TaskTestBase


class DummyTask(Task):
  """A task that appends the content of a Files's sources into its results_dir."""

  _implementation_version = 0
  _force_fail = False

  @property
  def incremental(self):
    return self._incremental

  @property
  def cache_target_dirs(self):
    return True

  @classmethod
  def implementation_version_str(cls):
    # NB: Intentionally ignoring `super` and returning a simplified version.
    return str(cls._implementation_version)

  # Enforces a single VT and returns a tuple of (vt, was_valid).
  def execute(self):
    with self.invalidated(self.context.targets()) as invalidation:
      assert len(invalidation.all_vts) == 1
      vt = invalidation.all_vts[0]
      was_valid = vt.valid
      if not was_valid:
        if vt.is_incremental:
          assert os.path.isdir(vt.previous_results_dir)
        for source in vt.target.sources_relative_to_buildroot():
          with open(os.path.join(get_buildroot(), source), 'r') as infile:
            outfile_name = os.path.join(vt.results_dir, source)
            with open(outfile_name, 'a') as outfile:
              outfile.write(infile.read())
        if self._force_fail:
          raise TaskError('Task forced to fail before updating vt state.')
        vt.update()
      return vt, was_valid


class FakeTask(Task):
  _impls = []

  @classmethod
  def implementation_version(cls):
    return super(FakeTask, cls).implementation_version() + cls._impls

  @classmethod
  def supports_passthru_args(cls):
    return True

  options_scope = 'fake-task'

  _deps = ()

  @classmethod
  def subsystem_dependencies(cls):
    return super(FakeTask, cls).subsystem_dependencies() + cls._deps

  def execute(self): pass


class OtherFakeTask(FakeTask):
  _other_impls = []

  @classmethod
  def supports_passthru_args(cls):
    return False

  @classmethod
  def implementation_version(cls):
    return super(OtherFakeTask, cls).implementation_version() + cls._other_impls

  options_scope = 'other-fake-task'


class FakeSubsystem(Subsystem):
  options_scope = 'fake-subsystem'

  @classmethod
  def register_options(cls, register):
    super(FakeSubsystem, cls).register_options(register)
    register('--fake-option', type=bool)


class AnotherFakeTask(Task):
  options_scope = 'another-fake-task'

  @classmethod
  def supports_passthru_args(cls):
    return True

  @classmethod
  def subsystem_dependencies(cls):
    return super(AnotherFakeTask, cls).subsystem_dependencies() + (FakeSubsystem.scoped(cls),)

  def execute(self): pass


class YetAnotherFakeTask(AnotherFakeTask):
  options_scope = 'yet-another-fake-task'

  @classmethod
  def supports_passthru_args(cls):
    return False


class TaskTest(TaskTestBase):

  _filename = 'f'
  _file_contents = 'results_string\n'
  _cachedir = 'local_artifact_cache'

  @classmethod
  def task_type(cls):
    return DummyTask

  def assertContent(self, vt, content):
    with open(os.path.join(vt.current_results_dir, self._filename), 'r') as f:
      self.assertEquals(f.read(), content)

  def _toggle_cache(self, enable_artifact_cache):
    cache_dir = self.create_dir(self._cachedir)
    self.set_options_for_scope(
      CacheSetup.options_scope,
      write_to=[cache_dir],
      read_from=[cache_dir],
      write=enable_artifact_cache,
      read=enable_artifact_cache,
    )

  def _fixture(self, incremental, options=None):
    target = self.make_target(':t', target_type=Files, sources=[self._filename])
    context = self.context(options=options, target_roots=[target])
    task = self.create_task(context)
    task._incremental = incremental
    return task, target

  def _run_fixture(self, content=None, incremental=False, artifact_cache=False, options=None):
    content = content or self._file_contents
    self._toggle_cache(artifact_cache)

    task, target = self._fixture(incremental=incremental, options=options)
    self._create_clean_file(target, content)
    vtA, was_valid = task.execute()
    return task, vtA, was_valid

  def _create_clean_file(self, target, content):
    self.create_file(self._filename, content)
    target.mark_invalidation_hash_dirty()

  def _cache_ignore_options(self, globally=False):
    return {
      'cache' + ('' if globally else '.' + self.options_scope): {
        'ignore': True
      }
    }

  def _synthesize_subtype(self, name='A', scope=None, cls=FakeTask, **kwargs):
    """Generate a synthesized subtype of `cls`."""
    if scope is None:
      scope = cls.options_scope
    subclass_name = b'test_{0}_{1}_{2}'.format(cls.__name__, scope, name)
    kwargs['options_scope'] = scope
    return type(subclass_name, (cls,), kwargs)

  def _instantiate_synthesized_type(self, task_type, **kwargs):
    """Generate a new instance of the synthesized type `task_type`."""
    ctx = super(TaskTestBase, self).context(for_task_types=[task_type], **kwargs)
    return task_type(ctx, self.test_workdir)

  def _task_type_to_fp(self, task_type, **kwargs):
    """Instantiate the `task_type` and return its fingerprint."""
    task_object = self._instantiate_synthesized_type(task_type, **kwargs)
    return task_object.fingerprint

  def _synth_fp(self, scope=None, cls=FakeTask, options_fingerprintable=None, **kwargs):
    """Synthesize a subtype of `cls`, instantiate it, and take its
    fingerprint. `options_fingerprintable` describes the registered options in
    their respective scopes which can contribute to the task fingerprint."""
    task_type = self._synthesize_subtype(scope=scope, cls=cls, **kwargs)
    return self._task_type_to_fp(
      task_type, options_fingerprintable=options_fingerprintable)

  def test_revert_after_failure(self):
    # Regression test to catch the following scenario:
    #
    # 1) In state A: Task suceeds and writes some output.  Key is recorded by the invalidator.
    # 2) In state B: Task fails, but writes some output.  Key is not recorded.
    # 3) After reverting back to state A: The current key is the same as the one recorded at the
    #    end of step 1), so it looks like no work needs to be done, but actually the task
    #    must re-run, to overwrite the output written in step 2.

    good_content = "good_content"
    bad_content = "bad_content"
    task, target = self._fixture(incremental=False)

    # Clean run succeeds.
    self._create_clean_file(target, good_content)
    vt, was_valid = task.execute()
    self.assertFalse(was_valid)
    self.assertContent(vt, good_content)

    # Change causes the task to fail.
    self._create_clean_file(target, bad_content)
    task._force_fail = True
    self.assertRaises(TaskError, task.execute)
    task._force_fail = False

    # Reverting to the previous content should invalidate, so the task
    # can reset any state created by the failed run.
    self._create_clean_file(target, good_content)
    vt, was_valid = task.execute()
    self.assertFalse(was_valid)
    self.assertContent(vt, good_content)

  def test_incremental(self):
    """Run three times with two unique fingerprints."""

    one = '1\n'
    two = '2\n'
    three = '3\n'
    task, target = self._fixture(incremental=True)

    # Clean - this is the first run so the VT is invalid.
    self._create_clean_file(target, one)
    vtA, was_A_valid = task.execute()
    self.assertFalse(was_A_valid)
    self.assertContent(vtA, one)

    # Changed the source file, so it copies the results from vtA.
    self._create_clean_file(target, two)
    vtB, was_B_valid = task.execute()
    self.assertFalse(was_B_valid)
    self.assertEqual(vtB.previous_cache_key, vtA.cache_key)
    self.assertContent(vtB, one + two)
    self.assertTrue(vtB.has_previous_results_dir)

    # Another changed source means a new cache_key. The previous_results_dir is copied.
    self._create_clean_file(target, three)
    vtC, was_C_valid = task.execute()
    self.assertFalse(was_C_valid)
    self.assertTrue(vtC.has_previous_results_dir)
    self.assertEqual(vtC.previous_results_dir, vtB.current_results_dir)
    self.assertContent(vtC, one + two + three)

    # Again create a clean file but this time reuse an old cache key - in this case vtB.
    self._create_clean_file(target, two)

    # This VT will be invalid, since there is no cache hit and it doesn't match the immediately
    # previous run. It will wipe the invalid vtB.current_results_dir and followup by copying in the
    # most recent results_dir, from vtC.
    vtD, was_D_valid = task.execute()
    self.assertFalse(was_D_valid)
    self.assertTrue(vtD.has_previous_results_dir)
    self.assertEqual(vtD.previous_results_dir, vtC.current_results_dir)
    self.assertContent(vtD, one + two + three + two)

    # And that the results_dir was stable throughout.
    self.assertEqual(vtA.results_dir, vtB.results_dir)
    self.assertEqual(vtB.results_dir, vtD.results_dir)

  def test_non_incremental(self):
    """Non-incremental should be completely unassociated."""

    one = '1\n'
    two = '2\n'
    task, target = self._fixture(incremental=False)

    # Run twice.
    self._create_clean_file(target, one)
    vtA, _ = task.execute()
    self.assertContent(vtA, one)
    self._create_clean_file(target, two)
    vtB, _ = task.execute()

    # Confirm two unassociated current directories with a stable results_dir.
    self.assertContent(vtA, one)
    self.assertContent(vtB, two)
    self.assertNotEqual(vtA.current_results_dir, vtB.current_results_dir)
    self.assertEqual(vtA.results_dir, vtB.results_dir)

  def test_implementation_version(self):
    """When the implementation version changes, previous artifacts are not available."""

    one = '1\n'
    two = '2\n'
    task, target = self._fixture(incremental=True)

    # Run twice, with a different implementation version the second time.
    DummyTask._implementation_version = 0
    self._create_clean_file(target, one)
    vtA, _ = task.execute()
    self.assertContent(vtA, one)
    DummyTask._implementation_version = 1
    self._create_clean_file(target, two)
    vtB, _ = task.execute()

    # No incrementalism.
    self.assertFalse(vtA.is_incremental)
    self.assertFalse(vtB.is_incremental)

    # Confirm two unassociated current directories, and unassociated stable directories.
    self.assertContent(vtA, one)
    self.assertContent(vtB, two)
    self.assertNotEqual(vtA.current_results_dir, vtB.current_results_dir)
    self.assertNotEqual(vtA.results_dir, vtB.results_dir)

  def test_execute_cleans_invalid_result_dirs(self):
    # Regression test to protect task.execute() from returning invalid dirs.
    task, vt, _ = self._run_fixture()
    self.assertNotEqual(os.listdir(vt.results_dir), [])
    self.assertTrue(os.path.islink(vt.results_dir))

    # Mimic the failure case, where an invalid task is run twice, due to failed download or
    # something.
    vt.force_invalidate()

    # But if this VT is invalid for a second run, the next invalidation deletes and recreates.
    self.assertTrue(os.path.islink(vt.results_dir))
    self.assertTrue(os.path.isdir(vt.current_results_dir))

  def test_cache_hit_short_circuits_incremental_copy(self):
    # Tasks should only copy over previous results if there is no cache hit, otherwise the copy is
    # wasted.
    first_contents = 'staid country photo'
    second_contents = 'shocking tabloid secret'

    self.assertFalse(self.buildroot_files(self._cachedir))
    # Initial run will have been invalid no cache hit, and with no previous_results_dir.
    task, vtA, was_A_valid = self._run_fixture(content=first_contents, incremental=True,
                                               artifact_cache=True)

    self.assertTrue(self.buildroot_files(self._cachedir))
    self.assertTrue(task.incremental)
    self.assertFalse(was_A_valid)

    # Invalidate and then execute with the same cache key.
    # Should be valid due to the artifact cache hit. No previous_results_dir will have been copied.
    vtA.force_invalidate()
    vtB, was_B_valid = task.execute()
    self.assertEqual(vtA.cache_key.hash, vtB.cache_key.hash)
    self.assertTrue(was_B_valid)
    self.assertFalse(vtB.has_previous_results_dir)

    # Change the cache_key and disable the cache_reads.
    # This results in an invalid vt, with no cache hit. It will then copy the vtB.previous_results
    # into vtC.results_dir.
    self._toggle_cache(False)
    self._create_clean_file(vtB.target, second_contents)

    vtC, was_C_valid = task.execute()
    self.assertNotEqual(vtB.cache_key.hash, vtC.cache_key.hash)
    self.assertEqual(vtC.previous_cache_key, vtB.cache_key)
    self.assertFalse(was_C_valid)

    self.assertTrue(vtC.has_previous_results_dir)
    self.assertEqual(vtB.current_results_dir, vtC.previous_results_dir)

    # Verify the content. The task was invalid twice - the initial run and the run with the changed
    # source file. Only vtC (previous sucessful runs + cache miss) resulted in copying the
    # previous_results.
    self.assertContent(vtC, first_contents + second_contents)

  # live_dirs() is in cache_manager, but like all of these tests, only makes sense to test as a
  # sequence of task runs.
  def test_live_dirs(self):
    task, vtA, _ = self._run_fixture(incremental=True)

    vtA_live = list(vtA.live_dirs())
    self.assertIn(vtA.results_dir, vtA_live)
    self.assertIn(vtA.current_results_dir, vtA_live)
    self.assertEqual(len(vtA_live), 2)

    self._create_clean_file(vtA.target, 'bar')
    vtB, _ = task.execute()
    vtB_live = list(vtB.live_dirs())

    # This time it contains the previous_results_dir.
    self.assertIn(vtB.results_dir, vtB_live)
    self.assertIn(vtB.current_results_dir, vtB_live)
    self.assertIn(vtA.current_results_dir, vtB_live)
    self.assertEqual(len(vtB_live), 3)

    # Delete vtB results_dir. live_dirs() should only return existing dirs, even if it knows the
    # previous_cache_key.
    safe_rmtree(vtB.current_results_dir)

    self._create_clean_file(vtB.target, 'baz')
    vtC, _ = task.execute()
    vtC_live = list(vtC.live_dirs())
    self.assertNotIn(vtB.current_results_dir, vtC_live)
    self.assertEqual(len(vtC_live), 2)

  def test_ignore_global(self):
    _, vtA, was_valid = self._run_fixture()
    self.assertFalse(was_valid)
    self.assertTrue(vtA.cacheable)

    self.reset_build_graph()
    _, vtA, was_valid = self._run_fixture()
    self.assertTrue(was_valid)
    self.assertTrue(vtA.cacheable)

    self.reset_build_graph()
    _, vtA, was_valid = self._run_fixture(options=self._cache_ignore_options(globally=True))
    self.assertFalse(was_valid)
    self.assertFalse(vtA.cacheable)

  def test_ignore(self):
    _, vtA, was_valid = self._run_fixture()
    self.assertFalse(was_valid)
    self.assertTrue(vtA.cacheable)

    self.reset_build_graph()
    _, vtA, was_valid = self._run_fixture()
    self.assertTrue(was_valid)
    self.assertTrue(vtA.cacheable)

    self.reset_build_graph()
    _, vtA, was_valid = self._run_fixture(options=self._cache_ignore_options())
    self.assertFalse(was_valid)
    self.assertFalse(vtA.cacheable)

  def test_fingerprint_identity(self):
    """Tasks formed with the same parameters should have the same fingerprint
    (smoke test)."""
    x = self._synth_fp()
    y = self._synth_fp()
    self.assertEqual(y, x)

  def test_fingerprint_implementation_version_single(self):
    """Tasks with a different implementation_version() should have different
    fingerprints."""
    empty_impls = self._synth_fp(_impls=[])
    zero_version = self._synth_fp(_impls=[('asdf', 0)])
    self.assertNotEqual(zero_version, empty_impls)
    one_version = self._synth_fp(_impls=[('asdf', 1)])
    self.assertNotEqual(one_version, empty_impls)
    alt_name_version = self._synth_fp(_impls=[('xxx', 0)])
    self.assertNotEqual(alt_name_version, zero_version)
    zero_one_version = self._synth_fp(_impls=[('asdf', 0), ('asdf', 1)])
    self.assertNotEqual(zero_one_version, zero_version)
    self.assertNotEqual(zero_one_version, one_version)

  def test_fingerprint_implementation_version_inheritance(self):
    """The implementation_version() of superclasses of the task should affect
    the task fingerprint."""
    versioned_fake = self._synth_fp(_impls=[('asdf', 0)])
    base_version_other_fake = self._synth_fp(
      cls=OtherFakeTask,
       _impls=[('asdf', 0)],
      _other_impls=[],
    )
    self.assertNotEqual(base_version_other_fake, versioned_fake)
    extended_version_other_fake = self._synth_fp(
      cls=OtherFakeTask,
       _impls=[('asdf', 0)],
      _other_impls=[('xxx', 0)],
    )
    self.assertNotEqual(extended_version_other_fake, base_version_other_fake)

    extended_version_copy = self._synth_fp(
      cls=OtherFakeTask,
       _impls=[('asdf', 1)],
      _other_impls=[('xxx', 0)],
    )
    self.assertNotEqual(extended_version_copy, extended_version_other_fake)

  def test_stable_name(self):
    """The stable_name() should be used to form the task fingerprint."""
    a_fingerprint = self._synth_fp(name='some_name', _stable_name='xxx')
    b_fingerprint = self._synth_fp(name='some_name', _stable_name='yyy')
    self.assertNotEqual(b_fingerprint, a_fingerprint)

  def test_fingerprint_changing_options_scope(self):
    """The options_scope of the task and any of its subsystem_dependencies
    should affect the task fingerprint."""
    task_fp = self._synth_fp(scope='xxx')
    other_task_fp = self._synth_fp(scope='yyy')
    self.assertNotEqual(other_task_fp, task_fp)

    subsystem_deps_fp = self._synth_fp(scope='xxx', _deps=(SubsystemDependency(FakeSubsystem, GLOBAL_SCOPE),))
    self.assertNotEqual(subsystem_deps_fp, task_fp)

    scoped_subsystems_fp = self._synth_fp(scope='xxx', _deps=(SubsystemDependency(FakeSubsystem, 'xxx'),))
    self.assertNotEqual(scoped_subsystems_fp, subsystem_deps_fp)

  def test_fingerprint_options_on_registered_scopes_only(self):
    """Changing or setting an option value should only affect the task
    fingerprint if it is registered as a fingerprintable option."""
    default_fp = self._synth_fp(cls=AnotherFakeTask, options_fingerprintable={})
    self.set_options_for_scope(
      AnotherFakeTask.options_scope, **{'fake-option': False})
    unregistered_option_fp = self._synth_fp(cls=AnotherFakeTask, options_fingerprintable={})
    self.assertEqual(unregistered_option_fp, default_fp)

    registered_option_fp = self._synth_fp(cls=AnotherFakeTask, options_fingerprintable={
      AnotherFakeTask.options_scope: {'fake-option': bool},
    })
    self.assertNotEqual(registered_option_fp, default_fp)

  def test_fingerprint_changing_option_value(self):
    """Changing an option value in some scope should affect the task
    fingerprint."""
    cur_option_spec = {
      AnotherFakeTask.options_scope: {'fake-option': bool},
    }
    self.set_options_for_scope(
      AnotherFakeTask.options_scope, **{'fake-option': False})
    task_opt_false_fp = self._synth_fp(cls=AnotherFakeTask, options_fingerprintable=cur_option_spec)
    self.set_options_for_scope(
      AnotherFakeTask.options_scope, **{'fake-option': True})
    task_opt_true_fp = self._synth_fp(cls=AnotherFakeTask, options_fingerprintable=cur_option_spec)
    self.assertNotEqual(task_opt_true_fp, task_opt_false_fp)

  def test_fingerprint_passthru_args(self):
    """Passthrough arguments should affect fingerprints iff the task
    supports passthrough args."""
    task_type_base = self._synthesize_subtype(cls=AnotherFakeTask)
    empty_passthru_args_fp = self._task_type_to_fp(
      task_type_base,
      passthru_args=[],
    )
    non_empty_passthru_args_fp = self._task_type_to_fp(
      task_type_base,
      passthru_args=['something'],
    )
    self.assertNotEqual(non_empty_passthru_args_fp, empty_passthru_args_fp)

    # YetAnotherFakeTask.supports_passthru_args() returns False
    task_type_derived_ignore_passthru = self._synthesize_subtype(cls=YetAnotherFakeTask)
    different_task_with_same_opts_fp = self._task_type_to_fp(
      task_type_derived_ignore_passthru,
      passthru_args=[],
    )
    different_task_with_passthru_fp = self._task_type_to_fp(
      task_type_derived_ignore_passthru,
      passthru_args=['asdf'],
    )
    self.assertEqual(different_task_with_passthru_fp, different_task_with_same_opts_fp)
