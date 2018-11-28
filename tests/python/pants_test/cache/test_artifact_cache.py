# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import open, str
from contextlib import contextmanager

from pants.cache.artifact import TarballArtifact
from pants.cache.artifact_cache import (NonfatalArtifactCacheError, call_insert,
                                        call_use_cached_files)
from pants.cache.local_artifact_cache import LocalArtifactCache, TempLocalArtifactCache
from pants.cache.pinger import BestUrlSelector, InvalidRESTfulCacheProtoError
from pants.cache.restful_artifact_cache import RESTfulArtifactCache
from pants.invalidation.build_invalidator import CacheKey
from pants.util.contextutil import temporary_dir, temporary_file, temporary_file_path
from pants.util.dirutil import safe_mkdir
from pants_test.cache.cache_server import cache_server
from pants_test.test_base import TestBase


TEST_CONTENT1 = b'muppet'
TEST_CONTENT2 = b'kermit'


class TestArtifactCache(TestBase):
  @contextmanager
  def setup_local_cache(self):
    with temporary_dir() as artifact_root:
      with temporary_dir() as cache_root:
        yield LocalArtifactCache(artifact_root, cache_root, compression=1)

  @contextmanager
  def setup_server(self, return_failed=False, cache_root=None):
    with cache_server(return_failed=return_failed, cache_root=cache_root) as server:
      yield server

  @contextmanager
  def setup_rest_cache(self, local=None, return_failed=False):
    with temporary_dir() as artifact_root:
      local = local or TempLocalArtifactCache(artifact_root, 0)
      with self.setup_server(return_failed=return_failed) as server:
        yield RESTfulArtifactCache(artifact_root, BestUrlSelector([server.url]), local)

  @contextmanager
  def setup_test_file(self, parent):
    with temporary_file(parent) as f:
      # Write the file.
      f.write(TEST_CONTENT1)
      path = f.name
      f.close()
      yield path

  def setUp(self):
    super(TestArtifactCache, self).setUp()
    # Init engine because decompression now goes through native code.
    self._init_engine()
    TarballArtifact.NATIVE_BINARY = self._scheduler._scheduler._native

  def test_local_cache(self):
    with self.setup_local_cache() as artifact_cache:
      self.do_test_artifact_cache(artifact_cache)

  def test_restful_cache(self):
    with self.assertRaises(InvalidRESTfulCacheProtoError):
      RESTfulArtifactCache('foo', BestUrlSelector(['ftp://localhost/bar']), 'foo')

    with self.setup_rest_cache() as artifact_cache:
      self.do_test_artifact_cache(artifact_cache)

  def test_restful_cache_failover(self):
    bad_url = 'http://badhost:123'

    with temporary_dir() as artifact_root:
      local = TempLocalArtifactCache(artifact_root, 0)

      # With fail-over, rest call second time will succeed
      with self.setup_server() as good_server:
        artifact_cache = RESTfulArtifactCache(artifact_root,
                                              BestUrlSelector([bad_url, good_server.url], max_failures=0),
                                              local)
        with self.assertRaises(NonfatalArtifactCacheError) as ex:
          self.do_test_artifact_cache(artifact_cache)
        self.assertIn('Failed to HEAD', str(ex.exception))

        self.do_test_artifact_cache(artifact_cache)

  def do_test_artifact_cache(self, artifact_cache):
    key = CacheKey('muppet_key', 'fake_hash')
    with self.setup_test_file(artifact_cache.artifact_root) as path:
      # Cache it.
      self.assertFalse(artifact_cache.has(key))
      self.assertFalse(bool(artifact_cache.use_cached_files(key)))
      artifact_cache.insert(key, [path])
      self.assertTrue(artifact_cache.has(key))

      # Stomp it.
      with open(path, 'wb') as outfile:
        outfile.write(TEST_CONTENT2)

      # Recover it from the cache.
      self.assertTrue(bool(artifact_cache.use_cached_files(key)))

      # Check that it was recovered correctly.
      with open(path, 'rb') as infile:
        content = infile.read()
      self.assertEqual(content, TEST_CONTENT1)

      # Delete it.
      artifact_cache.delete(key)
      self.assertFalse(artifact_cache.has(key))

  def test_local_backed_remote_cache(self):
    """make sure that the combined cache finds what it should and that it backfills"""
    with self.setup_server() as server:
      with self.setup_local_cache() as local:
        tmp = TempLocalArtifactCache(local.artifact_root, 0)
        remote = RESTfulArtifactCache(local.artifact_root, BestUrlSelector([server.url]), tmp)
        combined = RESTfulArtifactCache(local.artifact_root, BestUrlSelector([server.url]), local)

        key = CacheKey('muppet_key', 'fake_hash')

        with self.setup_test_file(local.artifact_root) as path:
          # No cache has key.
          self.assertFalse(local.has(key))
          self.assertFalse(remote.has(key))
          self.assertFalse(combined.has(key))

          # No cache returns key.
          self.assertFalse(bool(local.use_cached_files(key)))
          self.assertFalse(bool(remote.use_cached_files(key)))
          self.assertFalse(bool(combined.use_cached_files(key)))

          # Attempting to use key that no cache had should not change anything.
          self.assertFalse(local.has(key))
          self.assertFalse(remote.has(key))
          self.assertFalse(combined.has(key))

          # Add to only remote cache.
          remote.insert(key, [path])

          # After insertion to remote, remote and only remote should have key
          self.assertFalse(local.has(key))
          self.assertTrue(remote.has(key))
          self.assertTrue(combined.has(key))

          # Successfully using via remote should NOT change local.
          self.assertTrue(bool(remote.use_cached_files(key)))
          self.assertFalse(local.has(key))

          # Successfully using via combined SHOULD backfill local.
          self.assertTrue(bool(combined.use_cached_files(key)))
          self.assertTrue(local.has(key))
          self.assertTrue(bool(local.use_cached_files(key)))

  def test_local_backed_remote_cache_corrupt_artifact(self):
    """Ensure that a combined cache clears outputs after a failure to extract an artifact."""
    with temporary_dir() as remote_cache_dir:
      with self.setup_server(cache_root=remote_cache_dir) as server:
        with self.setup_local_cache() as local:
          tmp = TempLocalArtifactCache(local.artifact_root, compression=1)
          remote = RESTfulArtifactCache(local.artifact_root, BestUrlSelector([server.url]), tmp)
          combined = RESTfulArtifactCache(local.artifact_root, BestUrlSelector([server.url]), local)

          key = CacheKey('muppet_key', 'fake_hash')

          results_dir = os.path.join(local.artifact_root, 'a/sub/dir')
          safe_mkdir(results_dir)
          self.assertTrue(os.path.exists(results_dir))

          with self.setup_test_file(results_dir) as path:
            # Add to only the remote cache.
            remote.insert(key, [path])

            # Corrupt the artifact in the remote storage.
            self.assertTrue(server.corrupt_artifacts(r'.*muppet_key.*') == 1)

            # An attempt to read the corrupt artifact should fail.
            self.assertFalse(combined.use_cached_files(key, results_dir=results_dir))

            # The local artifact should not have been stored, and the results_dir should exist,
            # but be empty.
            self.assertFalse(local.has(key))
            self.assertTrue(os.path.exists(results_dir))
            self.assertTrue(len(os.listdir(results_dir)) == 0)

  def test_multiproc(self):
    key = CacheKey('muppet_key', 'fake_hash')

    with self.setup_local_cache() as cache:
      self.assertFalse(call_use_cached_files((cache, key, None)))
      with self.setup_test_file(cache.artifact_root) as path:
        call_insert((cache, key, [path], False))
      self.assertTrue(call_use_cached_files((cache, key, None)))

    with self.setup_rest_cache() as cache:
      self.assertFalse(call_use_cached_files((cache, key, None)))
      with self.setup_test_file(cache.artifact_root) as path:
        call_insert((cache, key, [path], False))
      self.assertTrue(call_use_cached_files((cache, key, None)))

  def test_failed_multiproc(self):
    key = CacheKey('muppet_key', 'fake_hash')

    # Failed requests should return failure status, but not raise exceptions
    with self.setup_rest_cache(return_failed=True) as cache:
      self.assertFalse(call_use_cached_files((cache, key, None)))
      with self.setup_test_file(cache.artifact_root) as path:
        call_insert((cache, key, [path], False))
      self.assertFalse(call_use_cached_files((cache, key, None)))

  def test_successful_request_cleans_result_dir(self):
    key = CacheKey('muppet_key', 'fake_hash')

    with self.setup_local_cache() as cache:
      self._do_test_successful_request_cleans_result_dir(cache, key)

    with self.setup_rest_cache() as cache:
      self._do_test_successful_request_cleans_result_dir(cache, key)

  def _do_test_successful_request_cleans_result_dir(self, cache, key):
    with self.setup_test_file(cache.artifact_root) as path:
      with temporary_dir() as results_dir:
        with temporary_file_path(root_dir=results_dir) as canary:
          call_insert((cache, key, [path], False))
          call_use_cached_files((cache, key, results_dir))
          # Results content should have been deleted.
          self.assertFalse(os.path.exists(canary))

  def test_failed_request_doesnt_clean_result_dir(self):
    key = CacheKey('muppet_key', 'fake_hash')
    with temporary_dir() as results_dir:
      with temporary_file_path(root_dir=results_dir) as canary:
        with self.setup_local_cache() as cache:
          self.assertFalse(
            call_use_cached_files((cache, key, results_dir)))
          self.assertTrue(os.path.exists(canary))

        with self.setup_rest_cache() as cache:
          self.assertFalse(
            call_use_cached_files((cache, key, results_dir)))
          self.assertTrue(os.path.exists(canary))

  def test_corrupted_cached_file_cleaned_up(self):
    key = CacheKey('muppet_key', 'fake_hash')

    with self.setup_local_cache() as artifact_cache:
      with self.setup_test_file(artifact_cache.artifact_root) as path:
        artifact_cache.insert(key, [path])
        tarfile = artifact_cache._cache_file_for_key(key)

        self.assertTrue(artifact_cache.use_cached_files(key))
        self.assertTrue(os.path.exists(tarfile))

        with open(tarfile, 'wb') as outfile:
          outfile.write(b'not a valid tgz any more')

        self.assertFalse(artifact_cache.use_cached_files(key))
        self.assertFalse(os.path.exists(tarfile))
