# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import multiprocessing
import os
import socket
import time
from BaseHTTPServer import HTTPServer
from contextlib import contextmanager
from SimpleHTTPServer import SimpleHTTPRequestHandler


@contextmanager
def zipfile_server():
  addr = ('[::1]', 3000)
  def run_server():
    os.chdir('contrib/go/examples/test_remote_zips/zipfiles/')
    handler_cls = SimpleHTTPRequestHandler
    handler_cls.protocol_version = 'HTTP/1.1'
    server_cls = HTTPServer
    server_cls.address_family = socket.AF_INET6
    server = server_cls(addr, handler_cls)
    server.serve_forever()
  p = multiprocessing.Process(target=run_server)
  p.start()
  # TODO(cgibb): There must be a better way of waiting for the server to start...
  time.sleep(2)
  yield addr
  p.terminate()


def get_zip_url(host, port, f):
  return 'http://{host}:{port}/github.com/fakeuser/{file}'.format(host=host, port=port, file=f)
