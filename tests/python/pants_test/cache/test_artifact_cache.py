# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import SimpleHTTPServer
import SocketServer
import unittest
from contextlib import contextmanager
from threading import Thread

from pants.base.build_invalidator import CacheKey
from pants.cache.artifact_cache import UnreadableArtifact, call_insert, call_use_cached_files
from pants.cache.local_artifact_cache import LocalArtifactCache, TempLocalArtifactCache
from pants.cache.restful_artifact_cache import InvalidRESTfulCacheProtoError, RESTfulArtifactCache
from pants.util.contextutil import pushd, temporary_dir, temporary_file
from pants.util.dirutil import safe_mkdir
from pants_test.base.context_utils import create_context


# A very trivial server that serves files under the cwd.
class SimpleRESTHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):
  def __init__(self, request, client_address, server):
    # The base class implements GET and HEAD.
    SimpleHTTPServer.SimpleHTTPRequestHandler.__init__(self, request, client_address, server)

  def do_HEAD(self):
    return SimpleHTTPServer.SimpleHTTPRequestHandler.do_HEAD(self)

  def do_PUT(self):
    path = self.translate_path(self.path)
    content_length = int(self.headers.getheader('content-length'))
    content = self.rfile.read(content_length)
    safe_mkdir(os.path.dirname(path))
    with open(path, 'wb') as outfile:
      outfile.write(content)
    self.send_response(200)
    self.end_headers()

  def do_DELETE(self):
    path = self.translate_path(self.path)
    if os.path.exists(path):
      os.unlink(path)
      self.send_response(200)
    else:
      self.send_error(404, 'File not found')
    self.end_headers()


class FailRESTHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):
  """Reject all requests"""

  def __init__(self, request, client_address, server):
    SimpleHTTPServer.SimpleHTTPRequestHandler.__init__(self, request, client_address, server)

  def _return_failed(self):
    self.send_response(401, 'Forced test failure')
    self.end_headers()

  def do_HEAD(self):
    return self._return_failed()

  def do_GET(self):
    return self._return_failed()

  def do_PUT(self):
    return self._return_failed()

  def do_DELETE(self):
    return self._return_failed()


TEST_CONTENT1 = 'muppet'
TEST_CONTENT2 = 'kermit'


class TestArtifactCache(unittest.TestCase):
  @contextmanager
  def setup_local_cache(self):
    with temporary_dir() as artifact_root:
      with temporary_dir() as cache_root:
        yield LocalArtifactCache(artifact_root, cache_root, compression=0)

  @contextmanager
  def setup_server(self, return_failed=False):
    httpd = None
    httpd_thread = None
    try:
      with temporary_dir() as cache_root:
        with pushd(cache_root):  # SimpleRESTHandler serves from the cwd.
          if return_failed:
            handler = FailRESTHandler
          else:
            handler = SimpleRESTHandler
          httpd = SocketServer.TCPServer(('localhost', 0), handler)
          port = httpd.server_address[1]
          httpd_thread = Thread(target=httpd.serve_forever)
          httpd_thread.start()
          yield 'http://localhost:{0}'.format(port)
    finally:
      if httpd:
        httpd.shutdown()
      if httpd_thread:
        httpd_thread.join()

  @contextmanager
  def setup_rest_cache(self, local=None, return_failed=False):
    with temporary_dir() as artifact_root:
      local = local or TempLocalArtifactCache(artifact_root, 0)
      with self.setup_server(return_failed=return_failed) as base_url:
        yield RESTfulArtifactCache(artifact_root, base_url, local)

  @contextmanager
  def setup_test_file(self, parent):
    with temporary_file(parent) as f:
      # Write the file.
      f.write(TEST_CONTENT1)
      path = f.name
      f.close()
      yield path

  def test_local_cache(self):
    with self.setup_local_cache() as artifact_cache:
      self.do_test_artifact_cache(artifact_cache)

  def test_restful_cache(self):
    with self.assertRaises(InvalidRESTfulCacheProtoError):
      RESTfulArtifactCache('foo', 'ftp://localhost/bar', 'foo')

    with self.setup_rest_cache() as artifact_cache:
      self.do_test_artifact_cache(artifact_cache)

  def do_test_artifact_cache(self, artifact_cache):
    key = CacheKey('muppet_key', 'fake_hash', 42)
    with self.setup_test_file(artifact_cache.artifact_root) as path:
      # Cache it.
      self.assertFalse(artifact_cache.has(key))
      self.assertFalse(bool(artifact_cache.use_cached_files(key)))
      artifact_cache.insert(key, [path])
      self.assertTrue(artifact_cache.has(key))

      # Stomp it.
      with open(path, 'w') as outfile:
        outfile.write(TEST_CONTENT2)

      # Recover it from the cache.
      self.assertTrue(bool(artifact_cache.use_cached_files(key)))

      # Check that it was recovered correctly.
      with open(path, 'r') as infile:
        content = infile.read()
      self.assertEquals(content, TEST_CONTENT1)

      # Delete it.
      artifact_cache.delete(key)
      self.assertFalse(artifact_cache.has(key))

  def test_local_backed_remote_cache(self):
    """make sure that the combined cache finds what it should and that it backfills"""
    with self.setup_server() as url:
      with self.setup_local_cache() as local:
        tmp = TempLocalArtifactCache(local.artifact_root, 0)
        remote = RESTfulArtifactCache(local.artifact_root, url, tmp)
        combined = RESTfulArtifactCache(local.artifact_root, url, local)

        key = CacheKey('muppet_key', 'fake_hash', 42)

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

  def test_multiproc(self):
    context = create_context()
    key = CacheKey('muppet_key', 'fake_hash', 42)

    with self.setup_local_cache() as cache:
      self.assertEquals(context.subproc_map(call_use_cached_files, [(cache, key)]), [False])
      with self.setup_test_file(cache.artifact_root) as path:
        context.subproc_map(call_insert, [(cache, key, [path], False)])
      self.assertEquals(context.subproc_map(call_use_cached_files, [(cache, key)]), [True])

    with self.setup_rest_cache() as cache:
      self.assertEquals(context.subproc_map(call_use_cached_files, [(cache, key)]), [False])
      with self.setup_test_file(cache.artifact_root) as path:
        context.subproc_map(call_insert, [(cache, key, [path], False)])
      self.assertEquals(context.subproc_map(call_use_cached_files, [(cache, key)]), [True])

  def test_failed_multiproc(self):
    context = create_context()
    key = CacheKey('muppet_key', 'fake_hash', 55)

    # Failed requests should return failure status, but not raise exceptions
    with self.setup_rest_cache(return_failed=True) as cache:
      self.assertFalse(context.subproc_map(call_use_cached_files, [(cache, key)])[0])
      with self.setup_test_file(cache.artifact_root) as path:
        context.subproc_map(call_insert, [(cache, key, [path], False)])
      self.assertFalse(context.subproc_map(call_use_cached_files, [(cache, key)])[0])
