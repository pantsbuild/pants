# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.build_environment import get_buildroot
from pants.base.payload import Payload
from pants.build_graph.target import Target
from pants.task.task import Task
from pants_test.tasks.task_test_base import TaskTestBase


class DummyLibrary(Target):
  def __init__(self, address, source, *args, **kwargs):
    payload = Payload()
    payload.add_fields({'sources': self.create_sources_field(sources=[source],
                                                             sources_rel_path=address.spec_path)})
    self.source = source
    super(DummyLibrary, self).__init__(address=address, payload=payload, *args, **kwargs)


class DummyTask(Task):
  """A task that appends the content of a DummyLibrary's source into its results_dir."""

  _implementation_version = 0

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

  def execute(self):
    with self.invalidated(self.context.targets()) as invalidation:
      assert len(invalidation.invalid_vts) == 1
      vt = invalidation.invalid_vts[0]
      if vt.is_incremental:
        assert os.path.isdir(vt.previous_results_dir)
      with open(os.path.join(get_buildroot(), vt.target.source), 'r') as infile:
        outfile_name = os.path.join(vt.results_dir, os.path.basename(vt.target.source))
        with open(outfile_name, 'a') as outfile:
          outfile.write(infile.read())
      vt.update()
      return vt


class TaskTest(TaskTestBase):

  _filename = 'f'
  _file_contents = 'results_string\n'

  @classmethod
  def task_type(cls):
    return DummyTask

  def assertContent(self, vt, content):
    with open(os.path.join(vt.current_results_dir, self._filename), 'r') as f:
      self.assertEquals(f.read(), content)

  def _fixture(self, incremental):
    target = self.make_target(':t', target_type=DummyLibrary, source=self._filename)
    context = self.context(target_roots=[target])
    task = self.create_task(context)
    task._incremental = incremental
    return target, task

  def _run_fixture(self, content=None, incremental=False):
    content = content or self._file_contents
    target, task = self._fixture(incremental=incremental)
    self._create_clean_file(target, content)
    vtA = task.execute()
    return target, task, vtA

  def _create_clean_file(self, target, content):
    self.create_file(self._filename, content)
    target.mark_invalidation_hash_dirty()

  # TODO(mateo): This test was relying on some implementation bugs and should probably be revisited, and either made
  # more representative of the common case or provided with some additional coverage.
  def test_incremental(self):
    """Run three times with two unique fingerprints."""

    one = '1\n'
    two = '2\n'
    target, task = self._fixture(incremental=True)

    # Clean.
    self._create_clean_file(target, one)
    vtA = task.execute()
    self.assertContent(vtA, one)

    # Cloned from vtA.
    self._create_clean_file(target, two)
    vtB = task.execute()
    self.assertContent(vtB, one + two)

    # vtC.previous_cache_key == vtB.cache_key so the task appends the file to vtB's results.
    # This behavior used to be skipped because the current_dir existed when checked by cache_manager._use_previous_dir.
    self._create_clean_file(target, one)
    vtC = task.execute()
    self.assertEqual(vtC.previous_cache_key, vtB.cache_key)
    self.assertContent(vtC, one + two + one)

    # Confirm that there were two unique results dirs, and that the second was cloned.
    self.assertContent(vtA, one + two + one)
    self.assertContent(vtB, one + two)
    self.assertContent(vtC, one + two + one)
    self.assertNotEqual(vtA.current_results_dir, vtB.current_results_dir)
    self.assertEqual(vtA.current_results_dir, vtC.current_results_dir)

    # And that the results_dir was stable throughout.
    self.assertEqual(vtA.results_dir, vtB.results_dir)
    self.assertEqual(vtB.results_dir, vtC.results_dir)

  def test_non_incremental(self):
    """Non-incremental should be completely unassociated."""

    one = '1\n'
    two = '2\n'
    target, task = self._fixture(incremental=False)

    # Run twice.
    self._create_clean_file(target, one)
    vtA = task.execute()
    self.assertContent(vtA, one)
    self._create_clean_file(target, two)
    vtB = task.execute()

    # Confirm two unassociated current directories with a stable results_dir.
    self.assertContent(vtA, one)
    self.assertContent(vtB, two)
    self.assertNotEqual(vtA.current_results_dir, vtB.current_results_dir)
    self.assertEqual(vtA.results_dir, vtB.results_dir)

  def test_implementation_version(self):
    """When the implementation version changes, previous artifacts are not available."""

    one = '1\n'
    two = '2\n'
    target, task = self._fixture(incremental=True)

    # Run twice, with a different implementation version the second time.
    DummyTask._implementation_version = 0
    self._create_clean_file(target, one)
    vtA = task.execute()
    self.assertContent(vtA, one)
    DummyTask._implementation_version = 1
    self._create_clean_file(target, two)
    vtB = task.execute()

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
    _, task, vt = self._run_fixture()
    self.assertNotEqual(os.listdir(vt.results_dir), [])
    self.assertTrue(os.path.islink(vt.results_dir))

    # Mimic the failure case, where an invalid task is run twice, due to failed download or something.
    vt.force_invalidate()

    # But if this VT is invalid for a second run, the next invalidation deletes and recreates.
    task.execute()
    self.assertTrue(os.path.islink(vt.results_dir))
    self.assertTrue(os.path.isdir(vt.current_results_dir))
