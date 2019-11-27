# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.http import HttpResponse, MakeHttpRequest
from pants.util.contextutil import http_server, temporary_dir
from http.server import BaseHTTPRequestHandler
from pants.engine.rules import RootRule
from pants.testutil.test_base import TestBase



class HttpHandlerForTests(BaseHTTPRequestHandler):
  response_text = b"www.pantsbuild.org"

  def do_HEAD(self):
    self.send_headers()

  def do_GET(self):
    self.send_headers()
    self.wfile.write(self.response_text)

  def send_headers(self):
    code = 200 if self.path == "/CNAME" else 404
    self.send_response(code)
    self.send_header("Content-Type", "text/utf-8")
    self.send_header("Content-Length", "{}".format(len(self.response_text)))
    self.end_headers()

class HttpIntrinsicTest(TestBase):

  @classmethod
  def rules(cls):
    return super().rules() + [
      RootRule(MakeHttpRequest),
    ]

  def test_basic(self):
    with http_server(HttpHandlerForTests) as port:
      url = f'http://localhost:{port}/'

      req = MakeHttpRequest()
      output, = self.scheduler.product_request(HttpResponse, subjects=[req])
      print(f"output: {output}")
      self.assertEqual(1, 2)

