# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import BaseHTTPServer
import os
import SocketServer
import unittest
from contextlib import closing, contextmanager
from threading import Thread

import mox
import requests
from six import StringIO

from pants.net.http.fetcher import Fetcher
from pants.util.contextutil import temporary_file


class FetcherTest(mox.MoxTestBase):
  def setUp(self):
    super(FetcherTest, self).setUp()

    self.requests = self.mox.CreateMockAnything()
    self.response = self.mox.CreateMock(requests.Response)
    self.fetcher = Fetcher(requests_api=self.requests)
    self.listener = self.mox.CreateMock(Fetcher.Listener)

  def expect_get(self, url, chunk_size_bytes, timeout_secs, listener=True):
    self.requests.get(url, allow_redirects=True, stream=True,
                      timeout=timeout_secs).AndReturn(self.response)
    self.response.status_code = 200
    self.response.headers = {'content-length': '11'}
    if listener:
      self.listener.status(200, content_length=11)

    chunks = ['0123456789', 'a']
    self.response.iter_content(chunk_size=chunk_size_bytes).AndReturn(chunks)
    return chunks

  def test_get(self):
    for chunk in self.expect_get('http://bar', chunk_size_bytes=1024, timeout_secs=60):
      self.listener.recv_chunk(chunk)
    self.listener.finished()
    self.response.close()

    self.mox.ReplayAll()

    self.fetcher.fetch('http://bar',
                       self.listener,
                       chunk_size_bytes=1024,
                       timeout_secs=60)

  def test_checksum_listener(self):
    digest = self.mox.CreateMockAnything()
    for chunk in self.expect_get('http://baz', chunk_size_bytes=1, timeout_secs=37):
      self.listener.recv_chunk(chunk)
      digest.update(chunk)

    self.listener.finished()
    digest.hexdigest().AndReturn('42')

    self.response.close()

    self.mox.ReplayAll()

    checksum_listener = Fetcher.ChecksumListener(digest=digest)
    self.fetcher.fetch('http://baz',
                       checksum_listener.wrap(self.listener),
                       chunk_size_bytes=1,
                       timeout_secs=37)
    self.assertEqual('42', checksum_listener.checksum)

  def test_download_listener(self):
    downloaded = ''
    for chunk in self.expect_get('http://foo', chunk_size_bytes=1048576, timeout_secs=3600):
      self.listener.recv_chunk(chunk)
      downloaded += chunk

    self.listener.finished()
    self.response.close()

    self.mox.ReplayAll()

    with closing(StringIO()) as fp:
      self.fetcher.fetch('http://foo',
                         Fetcher.DownloadListener(fp).wrap(self.listener),
                         chunk_size_bytes=1024 * 1024,
                         timeout_secs=60 * 60)
      self.assertEqual(downloaded, fp.getvalue())

  def test_size_mismatch(self):
    self.requests.get('http://foo', allow_redirects=True, stream=True,
                      timeout=60).AndReturn(self.response)
    self.response.status_code = 200
    self.response.headers = {'content-length': '11'}
    self.listener.status(200, content_length=11)

    self.response.iter_content(chunk_size=1024).AndReturn(['a', 'b'])
    self.listener.recv_chunk('a')
    self.listener.recv_chunk('b')

    self.response.close()

    self.mox.ReplayAll()

    with self.assertRaises(self.fetcher.Error):
      self.fetcher.fetch('http://foo',
                         self.listener,
                         chunk_size_bytes=1024,
                         timeout_secs=60)

  def test_get_error_transient(self):
    self.requests.get('http://foo', allow_redirects=True, stream=True,
                      timeout=60).AndRaise(requests.ConnectionError)

    self.mox.ReplayAll()

    with self.assertRaises(self.fetcher.TransientError):
      self.fetcher.fetch('http://foo',
                         self.listener,
                         chunk_size_bytes=1024,
                         timeout_secs=60)

  def test_get_error_permanent(self):
    self.requests.get('http://foo', allow_redirects=True, stream=True,
                      timeout=60).AndRaise(requests.TooManyRedirects)

    self.mox.ReplayAll()

    with self.assertRaises(self.fetcher.PermanentError) as e:
      self.fetcher.fetch('http://foo',
                         self.listener,
                         chunk_size_bytes=1024,
                         timeout_secs=60)
    self.assertTrue(e.exception.response_code is None)

  def test_http_error(self):
    self.requests.get('http://foo', allow_redirects=True, stream=True,
                      timeout=60).AndReturn(self.response)
    self.response.status_code = 404
    self.listener.status(404)

    self.response.close()

    self.mox.ReplayAll()

    with self.assertRaises(self.fetcher.PermanentError) as e:
      self.fetcher.fetch('http://foo',
                         self.listener,
                         chunk_size_bytes=1024,
                         timeout_secs=60)
    self.assertEqual(404, e.exception.response_code)

  def test_iter_content_error(self):
    self.requests.get('http://foo', allow_redirects=True, stream=True,
                      timeout=60).AndReturn(self.response)
    self.response.status_code = 200
    self.response.headers = {}
    self.listener.status(200, content_length=None)

    self.response.iter_content(chunk_size=1024).AndRaise(requests.Timeout)
    self.response.close()

    self.mox.ReplayAll()

    with self.assertRaises(self.fetcher.TransientError):
      self.fetcher.fetch('http://foo',
                         self.listener,
                         chunk_size_bytes=1024,
                         timeout_secs=60)

  def expect_download(self, path_or_fd=None):
    downloaded = ''
    for chunk in self.expect_get('http://1', chunk_size_bytes=13, timeout_secs=13, listener=False):
      downloaded += chunk
    self.response.close()

    self.mox.ReplayAll()

    path = self.fetcher.download('http://1',
                                 path_or_fd=path_or_fd,
                                 chunk_size_bytes=13,
                                 timeout_secs=13)
    return downloaded, path

  def test_download(self):
    downloaded, path = self.expect_download()
    try:
      with open(path) as fp:
        self.assertEqual(downloaded, fp.read())
    finally:
      os.unlink(path)

  def test_download_fd(self):
    with temporary_file() as fd:
      downloaded, path = self.expect_download(path_or_fd=fd)
      self.assertEqual(path, fd.name)
      fd.close()
      with open(path) as fp:
        self.assertEqual(downloaded, fp.read())

  def test_download_path(self):
    with temporary_file() as fd:
      fd.close()
      downloaded, path = self.expect_download(path_or_fd=fd.name)
      self.assertEqual(path, fd.name)
      with open(path) as fp:
        self.assertEqual(downloaded, fp.read())


class FetcherRedirectTest(unittest.TestCase):
  # NB(Eric Ayers): Using class variables like this seems horrible, but I can't figure out a better
  # to pass state between the test and the RedirectHTTPHandler class because it gets
  # re-instantiated on every request.
  _URL = None
  _URL2_ACCESSED = False
  _URL1_ACCESSED = False

  # A trivial HTTP server that serves up a redirect from /url2 --> /url1 and some hard-coded
  # responses in the HTTP message body.
  class RedirectHTTPHandler(BaseHTTPServer.BaseHTTPRequestHandler):

    def __init__(self, request, client_address, server):
      # The base class implements GET and HEAD.
      # Old-style class, so we must invoke __init__ this way.
      BaseHTTPServer.BaseHTTPRequestHandler.__init__(self, request, client_address, server)

    def do_GET(self):
      if self.path.endswith('url2'):
        self.send_response(302)
        redirect_url = '{}/url1'.format(FetcherRedirectTest._URL)
        self.send_header('Location',redirect_url)
        self.end_headers()
        self.wfile.write('\nredirecting you to {}'.format(redirect_url))
        FetcherRedirectTest._URL2_ACCESSED = True
      elif self.path.endswith('url1'):
        self.send_response(200)
        self.wfile.write('\nreturned from redirect')
        FetcherRedirectTest._URL1_ACCESSED = True
      else:
        self.send_response(404)
      self.end_headers()

  @contextmanager
  def setup_server(self, return_failed=False):
    httpd = None
    httpd_thread = None
    try:
      handler = self.RedirectHTTPHandler
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

  def test_download_redirect(self):
    """Make sure that a server that returns a redirect is actually followed.

    Test with a real HTTP server that redirects from one URL to another.
    """

    fetcher = Fetcher()
    with self.setup_server() as base_url:
      self._URL = base_url
      self.assertFalse(self._URL2_ACCESSED)
      self.assertFalse(self._URL1_ACCESSED)

      path = fetcher.download(base_url + '/url2')
      self.assertTrue(self._URL2_ACCESSED)
      self.assertTrue(self._URL1_ACCESSED)

      with open(path) as fp:
        self.assertEqual('returned from redirect\r\n', fp.read())
