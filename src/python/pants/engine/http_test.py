# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from typing import Dict, Iterator
from urllib.parse import parse_qs, urlparse

from pants.engine.http import HttpGetResponse, HttpRequester
from pants.testutil.test_base import TestBase
from pants.util.contextutil import http_server


class HttpHandlerForTests(BaseHTTPRequestHandler):
  response_text = b"A valid HTTP response!"
  not_found_text = b"Custom 404 page"
  server_failure_text = b"500 internal server error"

  def do_GET(self):
    self.send_headers()
    if self.path == "/valid-url":
      self.wfile.write(self.response_text)
    elif self.path == "/deliberate500":
      self.wfile.write(self.server_failure_text)
    elif "test-headers" in self.path:
      output = str(parse_qs(urlparse(self.path).query))
      self.wfile.write(output.encode())
    elif self.path == "/redirect":
      self.wfile.write(b"")
    else:
      self.wfile.write(self.not_found_text)

  def send_headers(self):
    if self.path == "/valid-url" or "/test-headers" in self.path:
      code = 200
    elif self.path == "/deliberate500":
      code = 500
    elif self.path == "/redirect":
      code = 302
    else:
      code = 404
    self.send_response(code)

    if self.path == "/redirect":
      self.send_header("Location", "/valid-url")

    self.send_header("Content-Type", "text/utf-8")

    self.end_headers()


class CachingTestHandler(BaseHTTPRequestHandler):
  count = 0

  def do_GET(self):
    self.send_response(200)
    self.end_headers()
    count = CachingTestHandler.count
    output = f"Your path: {self.path} count: {count}"
    CachingTestHandler.count += 1
    self.wfile.write(output.encode())


class HttpIntrinsicTest(TestBase):
  #
  #@classmethod
  #def rules(cls):
  #  return super().rules() + [
  #    RootRule(MakeHttpRequest),
  #  ]

  @contextmanager
  def make_request_to_path(self, path: str, headers: Dict[str, str] = ()) -> Iterator[HttpGetResponse]:
    with http_server(HttpHandlerForTests) as port:
      url = f'http://localhost:{port}/{path}'
      requester = HttpRequester()
      output = requester.get_request(url=url, headers=headers)
      yield (output, port)

  def test_200(self):
    with self.make_request_to_path("valid-url") as (response, port):
      assert response.status_code == 200
      assert response.output_bytes == b"A valid HTTP response!"
      assert response.url == f'http://localhost:{port}/valid-url'
      assert ('Content-Type', 'text/utf-8') in response.headers

  def test_302(self):
    with self.make_request_to_path("redirect") as (response, port):
      assert response.url == f"http://localhost:{port}/valid-url"

  def test_404(self):
    with self.make_request_to_path("nothingtheserverknowsabout") as (response, port):
      assert response.status_code == 404
      assert response.output_bytes == b"Custom 404 page"
      assert response.url == f'http://localhost:{port}/nothingtheserverknowsabout'

  def test_500(self):
    with self.make_request_to_path("deliberate500") as (response, port):
      assert response.status_code == 500
      assert response.output_bytes == b"500 internal server error"
      assert response.url == f'http://localhost:{port}/deliberate500'

  def test_custom_headers(self):
    headers = {"X-My-Custom-Header": "custom-info", "X-Other-Header": "more-info"}
    with self.make_request_to_path("test-headers", headers=headers) as (response, port):
      print(f"RESP: {response}")
      assert response.status_code == 200
      output = response.output_bytes.decode()
      assert "X-My-Custom-Header" in output
      assert "custom-info" in output
      assert "X-Other-Header" in output
      assert "more-info" in output
