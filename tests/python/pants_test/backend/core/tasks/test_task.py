# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pants.backend.core.tasks.task import Task
from pants.base.build_environment import get_buildroot
from pants.base.payload import Payload
from pants.build_graph.target import Target
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
      with open(os.path.join(get_buildroot(), vt.target.source), 'r') as infile:
        outfile_name = os.path.join(vt.results_dir, os.path.basename(vt.target.source))
        with open(outfile_name, 'a') as outfile:
          outfile.write(infile.read())
      vt.update()
      return vt


class TaskTest(TaskTestBase):
  @classmethod
  def task_type(cls):
    return DummyTask

  def assertContent(self, vt, filename, content):
    with open(os.path.join(vt.results_dir, filename), 'r') as f:
      self.assertEquals(f.read(), content)

  def _fixture(self, filename, incremental):
    target = self.make_target(':t', target_type=DummyLibrary, source=filename)
    context = self.context(target_roots=[target])
    task = self.create_task(context)
    task._incremental = incremental
    return target, task

  def test_incremental(self):
    f = 'f'
    target, task = self._fixture(f, incremental=True)

    # Run twice.
    self.create_file(f, '1\n')
    vt1 = task.execute()
    self.assertContent(vt1, f, '1\n')
    self.create_file(f, '2\n')
    target.mark_invalidation_hash_dirty(payload=True)
    vt2 = task.execute()

    # Confirm that there were two results dirs, and that the second was cloned
    self.assertContent(vt1, f, '1\n')
    self.assertContent(vt2, f, '1\n2\n')
    self.assertNotEqual(vt1.results_dir, vt2.results_dir)

  def test_non_incremental(self):
    f = 'f'
    target, task = self._fixture(f, incremental=False)

    # Run twice.
    self.create_file(f, '1\n')
    vt1 = task.execute()
    self.assertContent(vt1, f, '1\n')
    self.create_file(f, '2\n')
    target.mark_invalidation_hash_dirty(payload=True)
    vt2 = task.execute()

    # Confirm two unassociated directories.
    self.assertContent(vt1, f, '1\n')
    self.assertContent(vt2, f, '2\n')
    self.assertNotEqual(vt1.results_dir, vt2.results_dir)
