# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

import SimpleHTTPServer
import SocketServer

import os

from threading import Thread
from twitter.pants.base.artifact_cache import CombinedArtifactCache, FileBasedArtifactCache, \
  RESTfulArtifactCache, create_artifact_cache
from twitter.pants.base.build_invalidator import CacheKey
from twitter.common.contextutil import pushd, temporary_dir, temporary_file


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


def test_cache_spec_parsing():
  artifact_root = '/bogus/artifact/root'

  def check(expected_type, spec):
    cache = create_artifact_cache(None, artifact_root, spec)
    assert isinstance(cache, expected_type)
    assert cache.artifact_root == artifact_root

  with temporary_file() as temp:
    path = temp.name  # Must be a real path, since we safe_mkdir it.
    check(FileBasedArtifactCache, path)
    check(RESTfulArtifactCache, 'http://foo/bar')
    check(CombinedArtifactCache, [path, 'http://foo/bar'])


def test_local_cache():
  with temporary_dir() as artifact_root:
    with temporary_dir() as cache_root:
      artifact_cache = FileBasedArtifactCache(None, artifact_root, cache_root)
      do_test_artifact_cache(artifact_cache)

def test_restful_cache():
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
          artifact_cache = RESTfulArtifactCache(artifact_root, 'http://localhost:%d' % port)
          do_test_artifact_cache(artifact_cache)
  finally:
    if httpd:
      httpd.shutdown()
    if httpd_thread:
      httpd_thread.join()

def do_test_artifact_cache(artifact_cache):
  key = CacheKey('muppet_key', 'fake_hash', 42)
  with temporary_file(artifact_cache.artifact_root) as f:
    # Write the file.
    f.write(TEST_CONTENT1)
    path = f.name
    f.close()

    # Cache it.
    assert not artifact_cache.has(key)
    assert not artifact_cache.use_cached_files(key)
    artifact_cache.insert(key, [path])
    assert artifact_cache.has(key)

    # Stomp it.
    with open(path, 'w') as outfile:
      outfile.write(TEST_CONTENT2)

    # Recover it from the cache.
    assert artifact_cache.use_cached_files(key)

    # Check that it was recovered correctly.
    with open(path, 'r') as infile:
      content = infile.read()
    assert content == TEST_CONTENT1

    # Delete it.
    artifact_cache.delete(key)
    assert not artifact_cache.has(key)
