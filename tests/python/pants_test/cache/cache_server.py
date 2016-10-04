# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import SocketServer
from contextlib import contextmanager
from threading import Thread

from six.moves import SimpleHTTPServer

from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import safe_mkdir


# A very trivial server that serves files under the cwd.
class SimpleRESTHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):
  def __init__(self, request, client_address, server):
    # The base class implements GET and HEAD.
    # Old-style class, so we must invoke __init__ this way.
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
    # Old-style class, so we must invoke __init__ this way.
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


@contextmanager
def cache_server(return_failed=False, cache_root=None):
  httpd = None
  httpd_thread = None
  try:
    with temporary_dir() as tmpdir:
      cache_root = cache_root if cache_root else tmpdir
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
