# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from typing import Iterator, Tuple

from pants.engine.http import HttpResponse, MakeHttpRequest
from pants.engine.rules import RootRule
from pants.engine.scheduler import ExecutionError
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
    elif self.path == "/test-headers":
      self.wfile.write(str(self.headers).encode())
    elif self.path == "/redirect":
      self.wfile.write(b"")
    else:
      self.wfile.write(self.not_found_text)

  def send_headers(self):
    if self.path == "/valid-url" or self.path == "/test-headers":
      code = 200
    elif self.path == "/deliberate500":
      code = 500
    elif self.path == "/redirect":
      code = 302
      self.send_header("Location", "/valid-url")
    else:
      code = 404
    self.send_response(code)
    self.send_header("Content-Type", "text/utf-8")
    if self.path == "/broken-header":
      self.send_header(f"Content-Length", "deliberately-broken-header")
    self.end_headers()


class HttpIntrinsicTest(TestBase):
  @classmethod
  def rules(cls):
    return super().rules() + [
      RootRule(MakeHttpRequest),
    ]

  @contextmanager
  def make_request_to_path(self, path: str, headers: Tuple[str, ...] = ()) -> Iterator[HttpResponse]:
    with http_server(HttpHandlerForTests) as port:
      url = f'http://localhost:{port}/{path}'
      request = MakeHttpRequest(url=url, headers=headers)
      output = self.request_single_product(HttpResponse, request)
      yield (output, port)

  def test_200(self):
    with self.make_request_to_path("valid-url") as (response, port):
      assert response.response_code == 200
      assert response.output_bytes == b"A valid HTTP response!"
      assert response.url == f'http://localhost:{port}/valid-url'
      assert ('content-type', 'text/utf-8') in response.headers

  def test_302(self):
    with self.make_request_to_path("redirect") as (response, port):
      print(response)
      assert response.response_code == 444

  def test_404(self):
    with self.make_request_to_path("nothingtheserverknowsabout") as (response, port):
      assert response.response_code == 404
      assert response.output_bytes == b"Custom 404 page"
      assert response.url == f'http://localhost:{port}/nothingtheserverknowsabout'

  def test_500(self):
    with self.make_request_to_path("deliberate500") as (response, port):
      assert response.response_code == 500
      assert response.output_bytes == b"500 internal server error"
      assert response.url == f'http://localhost:{port}/deliberate500'

  def test_broken_header(self):
    with self.make_request_to_path("broken-header") as (response, port):
      assert response.response_code is None

  def test_custom_headers(self):
    headers = ("X-My-Custom-Header", "custom-info", "X-Other-Header", "more-info")
    with self.make_request_to_path("test-headers", headers=headers) as (response, port):
      assert response.response_code == 200
      output = response.output_bytes.decode()
      assert "x-my-custom-header: custom-info" in output
      assert "x-other-header: more-info" in output

  def test_malformed_header_specification(self):
    headers = ("X-My-Custom-Header", "custom-info", "X-Other-Header",)
    with self.assertRaises(ExecutionError) as cm:
      with self.make_request_to_path("test-headers", headers=headers) as (response, port):
        pass
    messages = cm.exception.end_user_messages()
    assert messages == ["Error parsing field 'headers': odd number of parts"]
