# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import SimpleHTTPServer
import SocketServer
import os
import unittest
from threading import Thread

from pants.base.build_invalidator import CacheKey
from pants.cache.cache_setup import create_artifact_cache, select_best_url
from pants.cache.combined_artifact_cache import CombinedArtifactCache
from pants.cache.local_artifact_cache import LocalArtifactCache
from pants.cache.restful_artifact_cache import RESTfulArtifactCache
from pants.util.contextutil import pushd, temporary_dir, temporary_file
from pants.util.dirutil import safe_mkdir
from pants_test.testutils.mock_logger import MockLogger


class MockPinger(object):
  def __init__(self, hosts_to_times):
    self._hosts_to_times = hosts_to_times
  # Returns a fake ping time such that the last host is always the 'fastest'.
  def pings(self, hosts):
    return map(lambda host: (host, self._hosts_to_times.get(host, 9999)), hosts)


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


TEST_CONTENT1 = 'muppet'
TEST_CONTENT2 = 'kermit'


class TestArtifactCache(unittest.TestCase):
  def test_select_best_url(self):
    spec = 'http://host1|https://host2:666/path/to|http://host3/path/'
    best = select_best_url(spec, MockPinger({'host1':  5, 'host2:666': 3, 'host3': 7}), MockLogger())
    self.assertEquals('https://host2:666/path/to', best)

  def test_cache_spec_parsing(self):
    artifact_root = '/bogus/artifact/root'

    def check(expected_type, spec):
      cache = create_artifact_cache(MockLogger(), artifact_root, spec, 'TestTask', 'testing')
      self.assertTrue(isinstance(cache, expected_type))
      self.assertEquals(cache.artifact_root, artifact_root)

    with temporary_dir() as tmpdir:
      cachedir = os.path.join(tmpdir, 'cachedir')  # Must be a real path, so we can safe_mkdir it.
      check(LocalArtifactCache, cachedir)
      check(RESTfulArtifactCache, 'http://localhost/bar')
      check(CombinedArtifactCache, [cachedir, 'http://localhost/bar'])


  def test_local_cache(self):
    with temporary_dir() as artifact_root:
      with temporary_dir() as cache_root:
        artifact_cache = LocalArtifactCache(None, artifact_root, cache_root)
        self.do_test_artifact_cache(artifact_cache)


  def test_restful_cache(self):
    httpd = None
    httpd_thread = None
    try:
      with temporary_dir() as cache_root:
        with pushd(cache_root):  # SimpleRESTHandler serves from the cwd.
          httpd = SocketServer.TCPServer(('localhost', 0), SimpleRESTHandler)
          port = httpd.server_address[1]
          httpd_thread = Thread(target=httpd.serve_forever)
          httpd_thread.start()
          with temporary_dir() as artifact_root:
            artifact_cache = RESTfulArtifactCache(MockLogger(), artifact_root,
                                                  'http://localhost:%d' % port)
            self.do_test_artifact_cache(artifact_cache)
    finally:
      if httpd:
        httpd.shutdown()
      if httpd_thread:
        httpd_thread.join()


  def do_test_artifact_cache(self, artifact_cache):
    key = CacheKey('muppet_key', 'fake_hash', 42, [])
    with temporary_file(artifact_cache.artifact_root) as f:
      # Write the file.
      f.write(TEST_CONTENT1)
      path = f.name
      f.close()

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
