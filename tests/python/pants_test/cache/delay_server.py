# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import http.server
import socketserver
import threading
import time


def get_delayed_handler(delay):
  class DelayResponseHandler(http.server.SimpleHTTPRequestHandler):
    def do_HEAD(self):
      time.sleep(delay)
      self.send_response(200)
      self.end_headers()

  return DelayResponseHandler


def setup_delayed_server(delay):
  server = socketserver.TCPServer(("", 0), get_delayed_handler(delay))
  thread = threading.Thread(target=server.serve_forever)
  thread.daemon = True
  thread.start()
  return server
