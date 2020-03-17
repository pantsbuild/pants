# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import unittest

from pants.cache.artifact import ArtifactError, DirectoryArtifact, TarballArtifact
from pants.testutil.test_base import TestBase
from pants.util.contextutil import temporary_dir
from pants.util.dirutil import safe_mkdir, safe_open


class TarballArtifactTest(TestBase):
    def setUp(self):
        super().setUp()
        # Init engine because decompression now goes through native code.
        self._init_engine()
        TarballArtifact.NATIVE_BINARY = self._scheduler._scheduler._native

    def test_get_paths_after_collect(self):
        with temporary_dir() as tmpdir:
            artifact_root = os.path.join(tmpdir, "artifacts")
            cache_root = os.path.join(tmpdir, "cache")
            safe_mkdir(cache_root)

            file_path = self.touch_file_in(artifact_root)

            artifact = TarballArtifact(
                artifact_root, artifact_root, os.path.join(cache_root, "some.tar")
            )
            artifact.collect([file_path])

            self.assertEqual([file_path], list(artifact.get_paths()))

    def test_does_not_exist_when_no_tar_file(self):
        with temporary_dir() as tmpdir:
            artifact_root = os.path.join(tmpdir, "artifacts")
            cache_root = os.path.join(tmpdir, "cache")
            safe_mkdir(cache_root)

            artifact = TarballArtifact(
                artifact_root, artifact_root, os.path.join(cache_root, "some.tar")
            )
            self.assertFalse(artifact.exists())

    def test_exists_true_when_exists(self):
        with temporary_dir() as tmpdir:
            artifact_root = os.path.join(tmpdir, "artifacts")
            cache_root = os.path.join(tmpdir, "cache")
            safe_mkdir(cache_root)

            path = self.touch_file_in(artifact_root)

            artifact = TarballArtifact(
                artifact_root, artifact_root, os.path.join(cache_root, "some.tar")
            )
            artifact.collect([path])

            self.assertTrue(artifact.exists())

    def test_non_existent_tarball_extraction(self):
        with temporary_dir() as tmpdir:
            artifact = TarballArtifact(
                artifact_root=tmpdir, artifact_extraction_root=tmpdir, tarfile_="vapor.tar"
            )
            with self.assertRaises(ArtifactError):
                artifact.extract()

    def test_corrupt_tarball_extraction(self):
        with temporary_dir() as tmpdir:
            path = self.touch_file_in(tmpdir, content="invalid")
            artifact = TarballArtifact(
                artifact_root=tmpdir, artifact_extraction_root=tmpdir, tarfile_=path
            )
            with self.assertRaises(ArtifactError):
                artifact.extract()

    def touch_file_in(self, artifact_root, content=""):
        path = os.path.join(artifact_root, "some.file")
        with safe_open(path, "w") as f:
            f.write(content)
        return path


class DirectoryArtifactTest(unittest.TestCase):
    def test_exists_when_dir_exists(self):
        with temporary_dir() as tmpdir:
            artifact_root = os.path.join(tmpdir, "artifacts")

            artifact_dir = os.path.join(tmpdir, "cache")
            safe_mkdir(artifact_dir)

            artifact = DirectoryArtifact(artifact_root, artifact_dir)
            self.assertTrue(artifact.exists())

    def test_does_not_exist_when_dir_missing(self):
        with temporary_dir() as tmpdir:
            artifact_root = os.path.join(tmpdir, "artifacts")

            artifact_dir = os.path.join(tmpdir, "cache")

            artifact = DirectoryArtifact(artifact_root, artifact_dir)
            self.assertFalse(artifact.exists())
