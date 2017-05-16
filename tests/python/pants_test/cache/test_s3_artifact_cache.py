# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from contextlib import contextmanager

import boto3
import pytest
from moto import mock_s3

from pants.cache.artifact_cache import UnreadableArtifact
from pants.cache.local_artifact_cache import LocalArtifactCache, TempLocalArtifactCache
from pants.cache.s3_artifact_cache import S3ArtifactCache
from pants.invalidation.build_invalidator import CacheKey
from pants.util.contextutil import temporary_dir, temporary_file
from pants.util.dirutil import safe_mkdir


_TEST_CONTENT1 = b'fraggle'
_TEST_CONTENT2 = b'gobo'

_TEST_BUCKET = 'verst-test-bucket'


@pytest.yield_fixture(scope="function")
def local_artifact_root():
  with temporary_dir() as artifact_root:
    yield artifact_root


@pytest.yield_fixture(scope="function")
def local_cache(local_artifact_root):
  with temporary_dir() as cache_root:
    yield LocalArtifactCache(
      local_artifact_root, cache_root, compression=1)


@pytest.fixture(
  scope="function",
  params=[True, False],
  ids=['temp-local-cache', 'local-cache']
)
def tmp_and_local_cache(request, local_artifact_root, local_cache):
  if request.param:
    return TempLocalArtifactCache(local_artifact_root, 0)
  else:
    return local_cache


@pytest.yield_fixture(scope="function", autouse=True)
def s3_fixture():
  mock_s3().start()

  try:
    s3 = boto3.resource('s3')
    s3.create_bucket(Bucket=_TEST_BUCKET)
    yield s3
  finally:
    mock_s3().stop()


@pytest.fixture(scope="function")
def s3_cache_instance(local_artifact_root, local_cache):
  with temporary_dir() as config_root:
    return S3ArtifactCache(
      os.path.join(config_root, 'non-existant'), None,
      local_artifact_root, 's3://' + _TEST_BUCKET, local_cache)


@pytest.fixture(scope="function")
def tmp_and_local_s3_cache_instance(
    local_artifact_root, tmp_and_local_cache):
  with temporary_dir() as config_root:
    return S3ArtifactCache(
      os.path.join(config_root, 'non-existant'), None,
      local_artifact_root, 's3://' + _TEST_BUCKET, tmp_and_local_cache)


@pytest.fixture()
def cache_key():
  return CacheKey('some_test_key', '1dfa0d08e47406038dda4ca5019c05c7977cb28c')


@pytest.yield_fixture()
def artifact_path(local_artifact_root):
  with setup_test_file(local_artifact_root) as path:
    yield path


@pytest.yield_fixture(scope="function")
def other_machine_cache():
  with temporary_dir() as artifact_root:
    with temporary_dir() as cache_root:
      local_cache = LocalArtifactCache(
        artifact_root, cache_root, compression=1)

      with temporary_dir() as config_root:
        yield S3ArtifactCache(
          os.path.join(config_root, 'non-existant'), None,
          artifact_root, 's3://' + _TEST_BUCKET, local_cache)


@contextmanager
def setup_test_file(parent):
  with temporary_file(parent) as f:
    # Write the file.
    f.write(_TEST_CONTENT1)
    path = f.name
    f.close()
    yield path


def test_basic_combined_cache(
    tmp_and_local_s3_cache_instance, cache_key, artifact_path):
  instance = tmp_and_local_s3_cache_instance
  assert not instance.has(cache_key)
  assert not instance.use_cached_files(cache_key)

  instance.insert(cache_key, [artifact_path])
  assert instance.has(cache_key)

  # Stomp it.
  with open(artifact_path, 'w') as outfile:
    outfile.write(_TEST_CONTENT2)

  # Recover it from the cache.
  assert instance.use_cached_files(cache_key)

  # Check that it was recovered correctly.
  with open(artifact_path, 'r') as infile:
    content = infile.read()
  assert content == _TEST_CONTENT1

  # Delete it.
  instance.delete(cache_key)
  assert not instance.has(cache_key)


def test_multi_machine_combined(
    s3_cache_instance, other_machine_cache, cache_key,
    local_cache, artifact_path):
  # Insert it into S3 from the other machine.
  other_machine_cache.insert(cache_key, [artifact_path])

  # Our machine doesn't have it ...
  assert not local_cache.has(cache_key)
  assert not local_cache.has(cache_key)

  # But can use it.
  assert s3_cache_instance.has(cache_key)
  assert s3_cache_instance.use_cached_files(cache_key)

  # And now we should have backfilled local:
  assert local_cache.has(cache_key)
  assert local_cache.use_cached_files(cache_key)


def test_corrupted_cached_file_cleaned_up(
    local_artifact_root,
    s3_fixture, s3_cache_instance, other_machine_cache,
    cache_key):
  local_results_dir = os.path.join(local_artifact_root, 'a/sub/dir')
  remote_results_dir = os.path.join(
    other_machine_cache.artifact_root, 'a/sub/dir')
  safe_mkdir(local_results_dir)
  safe_mkdir(remote_results_dir)
  assert os.path.exists(local_results_dir)
  assert os.path.exists(remote_results_dir)

  with setup_test_file(remote_results_dir) as path:
    other_machine_cache.insert(cache_key, [path])

    object = s3_fixture.Object(_TEST_BUCKET, s3_cache_instance._path_for_key(cache_key))
    object.put(Body=b'not a valid tgz any more')

    result = s3_cache_instance.use_cached_files(
      cache_key, results_dir=local_results_dir)

    assert isinstance(result, UnreadableArtifact)

    # The local artifact should not have been stored, and the results_dir should exist,
    # but be empty.

    assert os.path.exists(local_results_dir)
    assert len(os.listdir(local_results_dir)) == 0


def test_delete_non_existant_key(s3_cache_instance):
  s3_cache_instance.delete(CacheKey('foo', 'bar'))
  # Should not raise an exception


def test_use_cached_files_non_existant_key(s3_cache_instance):
  assert not s3_cache_instance.use_cached_files(CacheKey('foo', 'bar'))
