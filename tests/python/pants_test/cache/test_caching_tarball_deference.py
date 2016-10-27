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
from pants.util.dirutil import safe_open
from pants_test.tasks.task_test_base import TaskTestBase

SYMLINK_NAME = 'link'
DUMMY_FILE_NAME = 'dummy'
DUMMY_FILE_CONTENT = 'dummy_content'


class DummyCacheLibrary(Target):
  def __init__(self, address, source, *args, **kwargs):
    payload = Payload()
    payload.add_fields({'sources': self.create_sources_field(sources=[source],
                                                             sources_rel_path=address.spec_path)})
    self.source = source
    super(DummyCacheLibrary, self).__init__(address=address, payload=payload, *args, **kwargs)


class DummyCacheTask(Task):
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
        file_x = os.path.join(vt.results_dir, DUMMY_FILE_NAME)
        with safe_open(file_x, mode='wb') as fp:
          fp.write(DUMMY_FILE_CONTENT)
        symlink_y = os.path.join(vt.results_dir, SYMLINK_NAME)
        os.symlink(file_x, symlink_y)
      return invalidation.all_vts


class LocalCachingTarballDereferenceTest(TaskTestBase):
  _filename = 'f'

  @classmethod
  def task_type(cls):
    return DummyCacheTask

  def _get_artifact_path(self, vt):
    return "{}{}".format(
      os.path.join(self.artifact_cache, self.task.stable_name(), self.target.id, vt.cache_key.hash),
      '.tgz',
    )

  def _prepare_task(self, deference):
    self.artifact_cache = self.create_dir('artifact_cache')
    self.create_file(self._filename)
    self.set_options_for_scope(
      CacheSetup.options_scope,
      write_to=[self.artifact_cache],
      read_from=[self.artifact_cache],
      write=True,
      tarball_dereference=deference
    )
    self.target = self.make_target(':t', target_type=DummyCacheLibrary, source=self._filename)
    context = self.context(for_task_types=[DummyCacheTask], target_roots=[self.target])
    self.task = self.create_task(context)

  @staticmethod
  def _find_first_file_in_path(path, file_name):
    for root, dirs, files in os.walk(path):
      for file in files:
        if file == file_name:
          return os.path.join(root, file)

    return None

  def test_cache_written_without_deference(self):
    """
    Create target cache with dereference=False, and make sure the artifact contains the actual symlink.
    """
    self._prepare_task(deference=False)

    all_vts = self.task.execute()
    self.assertGreater(len(all_vts), 0)
    for vt in all_vts:
      artifact_address = self._get_artifact_path(vt)
      with temporary_dir() as tmpdir:
        with open_tar(artifact_address, 'r') as tarout:
          tarout.extractall(path=tmpdir)

        file_path = self._find_first_file_in_path(tmpdir, SYMLINK_NAME)
        self.assertIsNotNone(file_path, "Cannot find file {} in artifact {}".format(SYMLINK_NAME, artifact_address))
        self.assertTrue(
          os.path.islink(file_path),
          "{} in artifact {} should be a symlink but it is not.".format(SYMLINK_NAME, artifact_address)
        )

  def test_cache_written_with_deference(self):
    """
    Create target cache with dereference=True, and make sure the artifact's symlink is replaced by the content.
    """
    self._prepare_task(deference=True)

    all_vts = self.task.execute()
    self.assertGreater(len(all_vts), 0)
    for vt in all_vts:
      artifact_address = self._get_artifact_path(vt)
      with temporary_dir() as tmpdir:
        with open_tar(artifact_address, 'r') as tarout:
          tarout.extractall(path=tmpdir)
        file_path = self._find_first_file_in_path(tmpdir, SYMLINK_NAME)
        self.assertIsNotNone(file_path, "Cannot find file {} in artifact {}".format(SYMLINK_NAME, artifact_address))
        self.assertFalse(
          os.path.islink(file_path)
          , "{} in artifact {} should not be a symlink but it is.".format(SYMLINK_NAME, artifact_address)
        )
        with open(file_path, 'r') as f:
          self.assertEqual(DUMMY_FILE_CONTENT, f.read())
