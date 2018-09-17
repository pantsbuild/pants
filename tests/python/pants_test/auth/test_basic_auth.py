# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import base64
import os
import threading

from future.moves.http.server import BaseHTTPRequestHandler, HTTPServer

from pants.auth.basic_auth import BasicAuth, BasicAuthCreds
from pants.auth.cookies import Cookies
from pants.util.contextutil import environment_as, temporary_dir
from pants_test.test_base import TestBase


class RequestHandlerForTest(BaseHTTPRequestHandler):
  def do_GET(self):
    auth_header = self.headers.get('Authorization')
    assert auth_header is not None
    token_type, _, credentials = auth_header.partition(' ')
    assert token_type == 'Basic'
    username, password = base64.b64decode(credentials).decode('utf8').split(':')
    assert username == 'test_user'
    assert password == 'test_password'
    self.send_response(200)
    self.send_header('Set-Cookie', 'test_auth_key=test_auth_value; Max-Age=3600')
    self.end_headers()


def _run_test_server():
  httpd = HTTPServer(('localhost', 0), RequestHandlerForTest)
  thread = threading.Thread(target=httpd.serve_forever)
  thread.daemon = True
  thread.start()
  return httpd.server_port, httpd.shutdown


class TestBasicAuth(TestBase):
  def setUp(self):
    super(TestBasicAuth, self).setUp()
    self.port, shutdown_func = _run_test_server()
    self.addCleanup(shutdown_func)

  def _do_test_basic_auth(self, creds):
    with temporary_dir() as tmpcookiedir:
      cookie_file = os.path.join(tmpcookiedir, 'pants.test.cookies')

      self.context(for_subsystems=[BasicAuth, Cookies], options={
        BasicAuth.options_scope: {
          'providers': {
            'foobar': { 'url': 'http://localhost:{}'.format(self.port) }
          }
        },
        Cookies.options_scope: {
          'path': cookie_file
        }
      })

      basic_auth = BasicAuth.global_instance()
      cookies = Cookies.global_instance()

      self.assertListEqual([], list(cookies.get_cookie_jar()))
      basic_auth.authenticate(provider='foobar', creds=creds, cookies=cookies)
      cookies_list = list(cookies.get_cookie_jar())
      self.assertEqual(1, len(cookies_list))
      auth_cookie = cookies_list[0]
      self.assertEqual('test_auth_key', auth_cookie.name)
      self.assertEqual('test_auth_value', auth_cookie.value)

  def test_basic_auth_with_explicit_creds(self):
    self._do_test_basic_auth(creds=BasicAuthCreds('test_user', 'test_password'))

  def test_basic_auth_from_netrc(self):
    with temporary_dir(cleanup=False) as tmphomedir:
      with open(os.path.join(tmphomedir, '.netrc'), 'wb') as fp:
        fp.write('machine localhost\nlogin test_user\npassword test_password'.encode('ascii'))
      with environment_as(HOME=tmphomedir):
        self._do_test_basic_auth(creds=None)
