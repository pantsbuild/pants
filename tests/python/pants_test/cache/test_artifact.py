# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import unittest

from pants.cache.artifact import DirectoryArtifact, TarballArtifact
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_open


class TarballArtifactTest(unittest.TestCase):
  def test_get_paths_after_collect(self):
    with temporary_dir() as tmpdir:
      artifact_root = os.path.join(tmpdir, 'artifacts')
      cache_root = os.path.join(tmpdir, 'cache')
      safe_mkdir(cache_root)

      file_path = self.touch_file_in(artifact_root)

      artifact = TarballArtifact(artifact_root, os.path.join(cache_root, 'some.tar'))
      artifact.collect([file_path])

      self.assertEquals([file_path], list(artifact.get_paths()))

  def test_does_not_exist_when_no_tar_file(self):
    with temporary_dir() as tmpdir:
      artifact_root = os.path.join(tmpdir, 'artifacts')
      cache_root = os.path.join(tmpdir, 'cache')
      safe_mkdir(cache_root)

      artifact = TarballArtifact(artifact_root, os.path.join(cache_root, 'some.tar'))
      self.assertFalse(artifact.exists())

  def test_exists_true_when_exists(self):
    with temporary_dir() as tmpdir:
      artifact_root = os.path.join(tmpdir, 'artifacts')
      cache_root = os.path.join(tmpdir, 'cache')
      safe_mkdir(cache_root)

      path = self.touch_file_in(artifact_root)

      artifact = TarballArtifact(artifact_root, os.path.join(cache_root, 'some.tar'))
      artifact.collect([path])

      self.assertTrue(artifact.exists())

  def touch_file_in(self, artifact_root):
    path = os.path.join(artifact_root, 'some.file')
    with safe_open(path, 'w') as f:
      f.write('')
    return path


class DirectoryArtifactTest(unittest.TestCase):
  def test_exists_when_dir_exists(self):
    with temporary_dir() as tmpdir:
      artifact_root = os.path.join(tmpdir, 'artifacts')

      artifact_dir = os.path.join(tmpdir, 'cache')
      safe_mkdir(artifact_dir)

      artifact = DirectoryArtifact(artifact_root, artifact_dir)
      self.assertTrue(artifact.exists())

  def test_does_not_exist_when_dir_missing(self):
    with temporary_dir() as tmpdir:
      artifact_root = os.path.join(tmpdir, 'artifacts')

      artifact_dir = os.path.join(tmpdir, 'cache')

      artifact = DirectoryArtifact(artifact_root, artifact_dir)
      self.assertFalse(artifact.exists())
