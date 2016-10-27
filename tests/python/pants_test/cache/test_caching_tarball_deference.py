# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.base.payload import Payload
from pants.build_graph.target import Target
from pants.cache.cache_setup import CacheSetup
from pants.task.task import Task
from pants.util.contextutil import open_tar, temporary_dir
from pants.util.dirutil import safe_rmtree, safe_open
from pants_test.tasks.task_test_base import TaskTestBase

SYMLINK_NAME = 'link'


class DummyLibrary(Target):
  def __init__(self, address, source, *args, **kwargs):
    payload = Payload()
    payload.add_fields({'sources': self.create_sources_field(sources=[source],
                                                             sources_rel_path=address.spec_path)})
    self.source = source
    super(DummyLibrary, self).__init__(address=address, payload=payload, *args, **kwargs)


class DummyTask(Task):
  """A task that inserts a symlink into its results_dir."""
  options_scope = 'dummy'

  @property
  def cache_target_dirs(self):
    return True

  def execute(self):
    self._cache_factory.get_write_cache()
    # self._cache_factor
    with self.invalidated(self.context.targets()) as invalidation:
      for vt in invalidation.all_vts:
        print(vt.results_dir)
        file_x = os.path.join(vt.results_dir, 'dummy')
        with safe_open(file_x, mode='wb') as fp:
          fp.write('dummy')
        symlink_y = os.path.join(vt.results_dir, SYMLINK_NAME)
        os.symlink(file_x, symlink_y)
      return invalidation.all_vts, invalidation.invalid_vts


class LocalCachingTarballDereferenceTest(TaskTestBase):
  _filename = 'f'

  @classmethod
  def task_type(cls):
    return DummyTask

  def prepare_task(self, deference):
    self.artifact_cache = self.create_dir('artifact_cache')
    self.create_file(self._filename)
    self.set_options_for_scope(
      CacheSetup.options_scope,
      write_to=[self.artifact_cache],
      read_from=[self.artifact_cache],
      write=True,
      write_tarball_dereference=deference
    )
    self.target = self.make_target(':t', target_type=DummyLibrary, source=self._filename)
    context = self.context(for_task_types=[DummyTask], target_roots=[self.target])
    self.task = self.create_task(context)

  def test_cache_written_without_deference(self):
    self.prepare_task(deference=False)
    all_vts, invalid_vts = self.task.execute()
    self.assertGreater(len(invalid_vts), 0)
    for vt in invalid_vts:
      artifact_address = "{}{}".format(
        os.path.join(self.artifact_cache, self.task.stable_name(), self.target.id, vt.cache_key.hash),
        '.tgz',
      )
      print(artifact_address)
      with temporary_dir() as tmpdir:
        with open_tar(artifact_address, 'r') as tarout:
          tarout.extractall(path=tmpdir)

        for root, dirs, files in os.walk(tmpdir):
          for file in files:
            if file == SYMLINK_NAME:
              self.assertTrue(
                os.path.islink(os.path.join(root, file)),
                "{} in artifact {} should be a symlink but it is not.".format(SYMLINK_NAME, artifact_address)
              )
              return

        self.fail("Cannot find symlink {} in artifact {}".format(SYMLINK_NAME, artifact_address))

  def test_cache_written_with_deference(self):
    self.prepare_task(deference=True)
    all_vts, invalid_vts = self.task.execute()
    self.assertGreater(len(invalid_vts), 0)
    for vt in invalid_vts:
      artifact_address = "{}{}".format(
        os.path.join(self.artifact_cache, self.task.stable_name(), self.target.id, vt.cache_key.hash),
        '.tgz',
      )
      print(artifact_address)
      with temporary_dir() as tmpdir:
        with open_tar(artifact_address, 'r') as tarout:
          tarout.extractall(path=tmpdir)

        for root, dirs, files in os.walk(tmpdir):
          for file in files:
            if file == SYMLINK_NAME:
              self.assertFalse(
                os.path.islink(os.path.join(root, file))
                , "{} in artifact {} should not be a symlink but it is.".format(SYMLINK_NAME, artifact_address))
              return

        self.fail("Cannot find file {} in artifact {}".format(SYMLINK_NAME, artifact_address))
