# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import BaseHTTPServer
import json
import threading
import urlparse

from pants.goal.run_tracker import RunTracker
from pants_test.base_test import BaseTest


class RunTrackerTest(BaseTest):
  def test_upload_stats(self):
    stats = {'stats': {'foo': 'bar', 'baz': 42}}

    class Handler(BaseHTTPServer.BaseHTTPRequestHandler):
      def do_POST(handler):
        try:
          self.assertEquals('/upload', handler.path)
          self.assertEquals('application/x-www-form-urlencoded', handler.headers['Content-type'])
          length = int(handler.headers['Content-Length'])
          post_data = urlparse.parse_qs(handler.rfile.read(length).decode('utf-8'))
          decoded_post_data = {k: json.loads(v[0]) for k, v in post_data.items()}
          self.assertEquals(stats, decoded_post_data)
          handler.send_response(200)
        except Exception:
          handler.send_response(400)  # Ensure the main thread knows the test failed.
          raise


    server_address = ('', 0)
    server = BaseHTTPServer.HTTPServer(server_address, Handler)
    host, port = server.server_address

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    self.assertTrue(RunTracker.post_stats('http://{}:{}/upload'.format(host, port), stats))

    server.shutdown()
    server.server_close()
