# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from typing import Dict, Iterator, Optional, Tuple
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
      output = str(self.headers)
      self.wfile.write(output.encode())
    elif "test-query-params" in self.path:
      output = str(parse_qs(urlparse(self.path).query))
      self.wfile.write(output.encode())
    elif self.path == "/redirect":
      self.wfile.write(b"")
    else:
      self.wfile.write(self.not_found_text)

  def send_headers(self):
    p = self.path
    if any(["/valid-url" in p, "/test-headers" in p, "test-query-params" in p]):
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


class HttpIntrinsicTest(TestBase):

  @contextmanager
  def make_request_to_path(self, path: str, headers: Optional[Dict[str, str]] = None) -> Iterator[Tuple[HttpGetResponse, int]]:
    with http_server(HttpHandlerForTests) as port:
      url = f'http://localhost:{port}/{path}'
      requester = HttpRequester()
      output = requester.get_request(url=url, headers=headers)
      yield (output, port)

  def test_200(self) -> None:
    with self.make_request_to_path("valid-url") as (response, port):
      assert response.status_code == 200
      assert response.output_bytes == b"A valid HTTP response!"
      assert response.url == f'http://localhost:{port}/valid-url'
      assert ('Content-Type', 'text/utf-8') in response.headers

  def test_302(self) -> None:
    with self.make_request_to_path("redirect") as (response, port):
      assert response.url == f"http://localhost:{port}/valid-url"

  def test_404(self) -> None:
    with self.make_request_to_path("nothingtheserverknowsabout") as (response, port):
      assert response.status_code == 404
      assert response.output_bytes == b"Custom 404 page"
      assert response.url == f'http://localhost:{port}/nothingtheserverknowsabout'

  def test_500(self) -> None:
    with self.make_request_to_path("deliberate500") as (response, port):
      assert response.status_code == 500
      assert response.output_bytes == b"500 internal server error"
      assert response.url == f'http://localhost:{port}/deliberate500'

  def test_custom_headers(self) -> None:
    headers = {"X-My-Custom-Header": "custom-info", "X-Other-Header": "more-info"}
    with self.make_request_to_path("test-headers", headers=headers) as (response, port):
      assert response.status_code == 200
      assert response.output_bytes is not None
      output = response.output_bytes.decode()
      assert "X-My-Custom-Header: custom-info" in output
      assert "X-Other-Header: more-info" in output

  def test_query_params(self) -> None:
    with self.make_request_to_path("test-query-params?xxx=yyy") as (response, port):
      assert response.status_code == 200
      assert response.output_bytes is not None
      output = response.output_bytes.decode()
      assert "xxx" in output
      assert "yyy" in output
