# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
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
    with self.invalidated(self.context.targets()) as invalidation:
      for vt in invalidation.all_vts:
        if self.get_options().regular_file:
          # Create regular file.
          if self.get_options().regular_file_in_results_dir:
            regular_file_path = os.path.join(vt.results_dir, DUMMY_FILE_NAME)
          else:
            with temporary_dir(cleanup=False) as tmpdir:
              regular_file_path = os.path.join(tmpdir, DUMMY_FILE_NAME)

          with safe_open(regular_file_path, mode='wb') as fp:
            fp.write(DUMMY_FILE_CONTENT)
        else:
          # Generate a file path for the symlink but does not create the file.
          with temporary_dir() as tmpdir:
            regular_file_path = os.path.join(tmpdir, DUMMY_FILE_NAME)

        # Create a symlink to that file.
        symlink_y = os.path.join(vt.results_dir, SYMLINK_NAME)
        os.symlink(regular_file_path, symlink_y)
      return invalidation.all_vts


class LocalCachingTarballDereferenceTest(TaskTestBase):
  _filename = 'f'

  @classmethod
  def task_type(cls):
    return DummyCacheTask

  @staticmethod
  def _find_first_file_in_path(path, file_name):
    for root, dirs, files in os.walk(path):
      for file in files:
        if file == file_name:
          return os.path.join(root, file)

    return None

  def _get_artifact_path(self, vt):
    return "{}.tgz".format(
      os.path.join(self.artifact_cache, self.task.stable_name(), self.target.id, vt.cache_key.hash)
    )

  def _prepare_task(self, deference, regular_file, regular_file_in_results_dir):
    """
    Define task with caching with certain behaviors.

    :param deference: Specify whether task should dereference symlinks for `VersionedTarget`.
    :param regular_file: If True, a regular file will be created with some content as the dst of the symlink.
    :param regular_file_in_results_dir: If True, the regular file created will be in `results_dir`. Otherwise
                                        it will be somewhere random.
    """
    self.artifact_cache = self.create_dir('artifact_cache')
    self.create_file(self._filename)
    # Set up options for CacheSetup subsystem.
    self.set_options_for_scope(
      CacheSetup.options_scope,
      write_to=[self.artifact_cache],
      read_from=[self.artifact_cache],
      write=True,
      dereference_symlinks=deference,
    )

    # Set up options for DummyCacheTask as it is under TaskTestBase context.
    self.set_options_for_scope(
      TaskTestBase.options_scope,
      regular_file=regular_file,
      regular_file_in_results_dir=regular_file_in_results_dir
    )
    self.target = self.make_target(':t', target_type=DummyCacheLibrary, source=self._filename)
    context = self.context(for_task_types=[DummyCacheTask], target_roots=[self.target])
    self.task = self.create_task(context)

  def _assert_dereferenced_symlink_in_cache(self, all_vts):
    """
    Assert symlink is dereferenced when in the cache tarball.
    """
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

  # Cache creation should fail because the symlink destination is non-existent.
  def test_cache_dereference_no_file(self):
    self._prepare_task(deference=True, regular_file=False, regular_file_in_results_dir=False)
    with self.assertRaises(OSError):
      self.task.execute()

  # Symlink in cache should stay as a symlink
  def test_cache_no_dereference_no_file(self):
    self._prepare_task(deference=False, regular_file=False, regular_file_in_results_dir=False)

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
        # The destination of the symlink should be non-existent, hence IOError.
        with self.assertRaises(IOError):
          with open(file_path, 'r') as f:
            f.read()

  # Symlink in cache should stay as a symlink, and so does the dst file.
  def test_cache_no_dereference_file_inside_results_dir(self):
    self._prepare_task(deference=False, regular_file=True, regular_file_in_results_dir=True)

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
        with open(file_path, 'r') as f:
          self.assertEqual(DUMMY_FILE_CONTENT, f.read())

  def test_cache_dereference_file_inside_results_dir(self):
    self._prepare_task(deference=True, regular_file=True, regular_file_in_results_dir=True)

    all_vts = self.task.execute()
    self.assertGreater(len(all_vts), 0)
    self._assert_dereferenced_symlink_in_cache(all_vts)

  def test_cache_dereference_file_outside_results_dir(self):
    self._prepare_task(deference=True, regular_file=True, regular_file_in_results_dir=False)

    all_vts = self.task.execute()
    self.assertGreater(len(all_vts), 0)
    self._assert_dereferenced_symlink_in_cache(all_vts)
