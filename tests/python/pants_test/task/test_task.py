# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

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

  @property
  def incremental(self):
    return self._incremental

  @property
  def cache_target_dirs(self):
    return True

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

  @classmethod
  def task_type(cls):
    return DummyTask

  def assertContent(self, vt, content):
    with open(os.path.join(vt.results_dir, self._filename), 'r') as f:
      self.assertEquals(f.read(), content)

  def _fixture(self, incremental):
    target = self.make_target(':t', target_type=DummyLibrary, source=self._filename)
    context = self.context(target_roots=[target])
    task = self.create_task(context)
    task._incremental = incremental
    return target, task

  def _create_clean_file(self, target, content):
    self.create_file(self._filename, content)
    target.mark_invalidation_hash_dirty()

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

    # Incremental atop existing directory for vtA.
    self._create_clean_file(target, one)
    vtC = task.execute()
    self.assertContent(vtC, one + one)

    # Confirm that there were two results dirs, and that the second was cloned.
    self.assertContent(vtA, one + one)
    self.assertContent(vtB, one + two)
    self.assertContent(vtC, one + one)
    self.assertNotEqual(vtA.results_dir, vtB.results_dir)
    self.assertEqual(vtA.results_dir, vtC.results_dir)

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

    # Confirm two unassociated directories.
    self.assertContent(vtA, one)
    self.assertContent(vtB, two)
    self.assertNotEqual(vtA.results_dir, vtB.results_dir)
