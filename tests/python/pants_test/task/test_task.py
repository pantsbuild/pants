# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.base.payload import Payload
from pants.build_graph.target import Target
from pants.cache.cache_setup import CacheSetup
from pants.task.task import Task
from pants_test.tasks.task_test_base import TaskTestBase


class DummyLibrary(Target):
  def __init__(self, address, source, *args, **kwargs):
    payload = Payload()
    payload.add_fields({
      'sources': self.create_sources_field(sources=[source], sources_rel_path=address.spec_path)
    })
    self.source = source
    super(DummyLibrary, self).__init__(address=address, payload=payload, *args, **kwargs)


class DummyTask(Task):
  """A task that appends the content of a DummyLibrary's source into its results_dir."""

  _implementation_version = 0
  _cache_target_dirs = True
  _cache_incremental = False

  @property
  def cache_target_dirs(self):
    return self._cache_target_dirs

  @property
  def incremental(self):
    return self._incremental

  @property
  def cache_incremental(self):
    # Task.py has this hard-coded as False but it is exposed here to get coverage for when/if it's enabled.
    return self._cache_incremental

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
        with open(os.path.join(get_buildroot(), vt.target.source), 'r') as infile:
          outfile_name = os.path.join(vt.results_dir, os.path.basename(vt.target.source))
          with open(outfile_name, 'a') as outfile:
            outfile.write(infile.read())
        vt.update()
      return vt, was_valid


class TaskTest(TaskTestBase):

  _filename = 'f'
  _file_contents = 'results_string\n'
  _cachedir = 'local_artifact_cache'

  @classmethod
  def task_type(cls):
    return DummyTask

  def assertContent(self, vt, content):
    with open(os.path.join(vt.unique_results_dir, self._filename), 'r') as f:
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

  def _fixture(self, incremental):
    target = self.make_target(':t', target_type=DummyLibrary, source=self._filename)
    context = self.context(target_roots=[target])
    task = self.create_task(context)
    task._incremental = incremental
    return task, target

  def _run_fixture(self, content=None, incremental=False, artifact_cache=False):
    content = content or self._file_contents
    self._toggle_cache(artifact_cache)

    task, target = self._fixture(incremental=incremental)
    self._create_clean_file(target, content)
    vtA, was_valid = task.execute()
    return task, vtA, was_valid

  def _create_clean_file(self, target, content):
    self.create_file(self._filename, content)
    target.mark_invalidation_hash_dirty()

  def test_incremental(self):
    """Run three times with two unique fingerprints."""
    # Uses private API of the VT, vt._previous_results_dir. Not ideal, but that property is totally dependent on
    # running a sequence of task executions. Being tested here is more evidence the abstraction leaks a bit.
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
    self.assertEqual(vtB._previous_results_dir, vtA.unique_results_dir)
    self.assertEqual(vtB._previous_cache_key, vtA.cache_key)
    self.assertContent(vtB, one + two)

    # Another changed source means a new cache_key. The previous_results_dir is copied.
    self._create_clean_file(target, three)
    vtC, was_C_valid = task.execute()
    self.assertFalse(was_C_valid)
    self.assertEqual(vtC._previous_results_dir, vtB.unique_results_dir)
    self.assertContent(vtC, one + two + three)

    # Again create a clean file but this time reuse an old cache key - in this case vtB.
    self._create_clean_file(target, two)

    # This VT will be invalid, since there is no cache hit and it doesn't match the immediately previous run.
    # It will wipe the invalid vtB.unique_results_dir and followup by copying in the most recent results_dir, from vtC.
    vtD, was_D_valid = task.execute()
    self.assertFalse(was_D_valid)
    self.assertEqual(vtD._previous_results_dir, vtC.unique_results_dir)
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
    self.assertNotEqual(vtA.unique_results_dir, vtB.unique_results_dir)
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
    self.assertFalse(self._incremental_vt(vtA))
    self.assertFalse(self._incremental_vt(vtB))

    # Confirm two unassociated current directories, and unassociated stable directories.
    self.assertContent(vtA, one)
    self.assertContent(vtB, two)
    self.assertNotEqual(vtA.unique_results_dir, vtB.unique_results_dir)
    self.assertNotEqual(vtA.results_dir, vtB.results_dir)

  def test_execute_cleans_invalid_result_dirs(self):
    # Regression test to protect task.execute() from returning invalid dirs.
    task, vt,  _ = self._run_fixture()
    self.assertNotEqual(os.listdir(vt.results_dir), [])
    self.assertTrue(os.path.islink(vt.results_dir))

    # Mimic the failure case, where an invalid task is run twice, due to failed download or something.
    vt.force_invalidate()

    # But if this VT is invalid for a second run, the next invalidation deletes and recreates.
    self.assertTrue(os.path.islink(vt.results_dir))
    self.assertTrue(os.path.isdir(vt.unique_results_dir))

  def test_cache_hit_short_circuits_incremental_copy(self):
    # Tasks should only copy over previous results if there is no cache hit, otherwise the copy is wasted.
    first_contents = 'staid country photo'
    second_contents = 'shocking tabloid secret'

    self.assertFalse(self.buildroot_files(self._cachedir))
    # Initial run will have been invalid no cache hit, and with no previous_results_dir.
    task, vtA, was_A_valid = self._run_fixture(content=first_contents, incremental=True, artifact_cache=True)

    self.assertTrue(self.buildroot_files(self._cachedir))
    self.assertTrue(task.incremental)
    self.assertFalse(was_A_valid)

    # Invalidate and then execute with the same cache key.
    # Should be valid due to the artifact cache hit. No previous_results_dir will have been copied.
    vtA.force_invalidate()
    vtB, was_B_valid = task.execute()
    self.assertEqual(vtA.cache_key.hash, vtB.cache_key.hash)
    self.assertTrue(was_B_valid)
    self.assertFalse(self._incremental_vt(vtB))

    # Change the cache_key and disable the cache_reads.
    # This results in an invalid vt, with no cache hit. It will then copy the vtB.previous_results into vtC.results_dir.
    self._toggle_cache(False)
    self._create_clean_file(vtB.target, second_contents)

    vtC, was_C_valid = task.execute()
    self.assertNotEqual(vtB.cache_key.hash, vtC.cache_key.hash)
    self.assertEqual(vtC._previous_cache_key, vtB.cache_key)
    self.assertFalse(was_C_valid)

    # Verify the content. The task was invalid twice - the initial run and the run with the changed source file.
    # Only vtC (previous sucessful runs + cache miss) resulted in copying the previous_results.
    self.assertContent(vtC, first_contents + second_contents)

  # Some sanity checks around the should_cache bool, since I am tired of only finding out it broke through int tests!
  # The should_cache_target_dir inherited a bug from the CacheFactory - success returns a cache instance. So, we deal.
  def test_should_cache_if_cache_available(self):
    task, vtA, _ = self._run_fixture(artifact_cache=True)
    self.assertIsNotNone(task._should_cache_target_dir(vtA))

  def test_should_not_cache_if_not_cache_target_dirs(self):
    task, vtA, _ = self._run_fixture(artifact_cache=True)
    self.assertTrue(task.cache_target_dirs)
    task._cache_target_dirs = False
    self.assertFalse(task.cache_target_dirs)
    self.assertFalse(task._should_cache_target_dir(vtA))

  def test_should_cache_clean_incremental_build(self):
    task, vtA, _ = self._run_fixture(incremental=True, artifact_cache=True)
    self.assertIsNotNone(task._should_cache_target_dir(vtA))

  def test_disable_cache_when_created_from_incremental_results(self):
    task, vtA, _ = self._run_fixture(incremental=True, artifact_cache=True)
    self._create_clean_file(vtA.target, 'bar')
    vtB, _ = task.execute()
    self.assertFalse(task._should_cache_target_dir(vtB))

  def test_enable_cache_when_created_from_incremental_results(self):
    task, vtA, _ = self._run_fixture(incremental=True, artifact_cache=True)
    self._create_clean_file(vtA.target, 'bar')
    task._cache_incremental = True
    vtB, _ = task.execute()
    self.assertTrue(task._should_cache_target_dir(vtB))

  def test_should_not_cache_if_no_available_cache(self):
    task, vtA, _ = self._run_fixture(incremental=True, artifact_cache=False)
    self.assertFalse(task._should_cache_target_dir(vtA))

  def test_should_respect_no_cache_label(self):
    task, vtA, _ = self._run_fixture(incremental=True, artifact_cache=True)
    self.assertIsNotNone(task._should_cache_target_dir(vtA))
    vtA.target.add_labels('no_cache')
    self.assertFalse(task._should_cache_target_dir(vtA))

