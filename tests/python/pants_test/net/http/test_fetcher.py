# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import hashlib
import http.server
import os
import socketserver
import unittest
from builtins import open, str
from contextlib import closing, contextmanager
from functools import reduce
from io import BytesIO
from threading import Thread

import mock
import requests

from pants.net.http.fetcher import Fetcher
from pants.util.contextutil import temporary_dir, temporary_file
from pants.util.dirutil import safe_open, touch


class FetcherTest(unittest.TestCase):
  def setUp(self):
    self.requests = mock.Mock(spec=requests.Session)
    self.response = mock.Mock(spec=requests.Response)
    self.fetcher = Fetcher('/unused/root/dir', requests_api=self.requests)
    self.listener = mock.create_autospec(Fetcher.Listener, spec_set=True)

  def status_call(self, status_code, content_length=None):
    return mock.call.status(status_code, content_length=content_length)

  def ok_call(self, chunks):
    return self.status_call(200, content_length=sum(len(c) for c in chunks))

  def assert_listener_calls(self, expected_listener_calls, chunks, expect_finished=True):
    expected_listener_calls.extend(mock.call.recv_chunk(chunk) for chunk in chunks)
    if expect_finished:
      expected_listener_calls.append(mock.call.finished())
    self.assertEqual(expected_listener_calls, self.listener.method_calls)

  def assert_local_file_fetch(self, url_prefix=''):
    chunks = [b'0123456789', b'a']
    with temporary_file() as fp:
      for chunk in chunks:
        fp.write(chunk)
      fp.close()

      self.fetcher.fetch(url_prefix + fp.name, self.listener, chunk_size_bytes=10)

      self.assert_listener_calls([self.ok_call(chunks)], chunks)
      self.requests.assert_not_called()

  def test_file_path(self):
    self.assert_local_file_fetch()

  def test_file_scheme(self):
    self.assert_local_file_fetch('file:')

  def assert_local_file_fetch_relative(self, url, *rel_path):
    expected_contents = b'proof'
    with temporary_dir() as root_dir:
      with safe_open(os.path.join(root_dir, *rel_path), 'wb') as fp:
        fp.write(expected_contents)
      with temporary_file() as download_fp:
        Fetcher(root_dir).download(url, path_or_fd=download_fp)
        download_fp.close()
        with open(download_fp.name, 'rb') as fp:
          self.assertEqual(expected_contents, fp.read())

  def test_file_scheme_double_slash_relative(self):
    self.assert_local_file_fetch_relative('file://relative/path', 'relative', 'path')

  def test_file_scheme_embedded_double_slash(self):
    self.assert_local_file_fetch_relative('file://a//strange//path', 'a', 'strange', 'path')

  def test_file_scheme_triple_slash(self):
    self.assert_local_file_fetch('file://')

  def test_file_dne(self):
    with temporary_dir() as base:
      with self.assertRaises(self.fetcher.PermanentError):
        self.fetcher.fetch(os.path.join(base, 'dne'), self.listener)

  def test_file_no_perms(self):
    with temporary_dir() as base:
      no_perms = os.path.join(base, 'dne')
      touch(no_perms)
      os.chmod(no_perms, 0)
      self.assertTrue(os.path.exists(no_perms))
      with self.assertRaises(self.fetcher.PermanentError):
        self.fetcher.fetch(no_perms, self.listener)

  @contextmanager
  def expect_get(self, url, chunk_size_bytes, timeout_secs, chunks=None, listener=True):
    chunks = chunks or [b'0123456789', b'a']
    size = sum(len(c) for c in chunks)

    self.requests.get.return_value = self.response
    self.response.status_code = 200
    self.response.headers = {'content-length': str(size)}
    self.response.iter_content.return_value = chunks

    yield chunks, [self.ok_call(chunks)] if listener else []

    self.requests.get.expect_called_once_with(url, allow_redirects=True, stream=True,
                                              timeout=timeout_secs)
    self.response.iter_content.expect_called_once_with(chunk_size=chunk_size_bytes)

  def test_get(self):
    with self.expect_get('http://bar',
                         chunk_size_bytes=1024,
                         timeout_secs=60) as (chunks, expected_listener_calls):

      self.fetcher.fetch('http://bar',
                         self.listener,
                         chunk_size_bytes=1024,
                         timeout_secs=60)

      self.assert_listener_calls(expected_listener_calls, chunks)
      self.response.close.expect_called_once_with()

  def test_checksum_listener(self):
    digest = mock.Mock(spec=hashlib.md5())
    digest.hexdigest.return_value = '42'
    checksum_listener = Fetcher.ChecksumListener(digest=digest)

    with self.expect_get('http://baz',
                         chunk_size_bytes=1,
                         timeout_secs=37) as (chunks, expected_listener_calls):

      self.fetcher.fetch('http://baz',
                         checksum_listener.wrap(self.listener),
                         chunk_size_bytes=1,
                         timeout_secs=37)

    self.assertEqual('42', checksum_listener.checksum)

    def expected_digest_calls():
      for chunk in chunks:
        yield mock.call.update(chunk)
      yield mock.call.hexdigest()

    self.assertEqual(list(expected_digest_calls()), digest.method_calls)

    self.assert_listener_calls(expected_listener_calls, chunks)
    self.response.close.assert_called_once_with()

  def concat_chunks(self, chunks):
    return reduce(lambda acc, c: acc + c, chunks, b'')

  def test_download_listener(self):
    with self.expect_get('http://foo',
                         chunk_size_bytes=1048576,
                         timeout_secs=3600) as (chunks, expected_listener_calls):

      with closing(BytesIO()) as fp:
        self.fetcher.fetch('http://foo',
                           Fetcher.DownloadListener(fp).wrap(self.listener),
                           chunk_size_bytes=1024 * 1024,
                           timeout_secs=60 * 60)

        downloaded = self.concat_chunks(chunks)
        self.assertEqual(downloaded, fp.getvalue())

    self.assert_listener_calls(expected_listener_calls, chunks)
    self.response.close.assert_called_once_with()

  def test_size_mismatch(self):
    self.requests.get.return_value = self.response
    self.response.status_code = 200
    self.response.headers = {'content-length': '11'}
    chunks = ['a', 'b']
    self.response.iter_content.return_value = chunks

    with self.assertRaises(self.fetcher.Error):
      self.fetcher.fetch('http://foo',
                         self.listener,
                         chunk_size_bytes=1024,
                         timeout_secs=60)

    self.requests.get.assert_called_once_with('http://foo', allow_redirects=True, stream=True,
                                              timeout=60)
    self.response.iter_content.assert_called_once_with(chunk_size=1024)
    self.assert_listener_calls([self.status_call(200, content_length=11)], chunks,
                               expect_finished=False)
    self.response.close.assert_called_once_with()

  def test_get_error_transient(self):
    self.requests.get.side_effect = requests.ConnectionError

    with self.assertRaises(self.fetcher.TransientError):
      self.fetcher.fetch('http://foo',
                         self.listener,
                         chunk_size_bytes=1024,
                         timeout_secs=60)

    self.requests.get.assert_called_once_with('http://foo', allow_redirects=True, stream=True,
                                              timeout=60)

  def test_get_error_permanent(self):
    self.requests.get.side_effect = requests.TooManyRedirects

    with self.assertRaises(self.fetcher.PermanentError) as e:
      self.fetcher.fetch('http://foo',
                         self.listener,
                         chunk_size_bytes=1024,
                         timeout_secs=60)

    self.assertTrue(e.exception.response_code is None)
    self.requests.get.assert_called_once_with('http://foo', allow_redirects=True, stream=True,
                                              timeout=60)

  def test_http_error(self):
    self.requests.get.return_value = self.response
    self.response.status_code = 404

    with self.assertRaises(self.fetcher.PermanentError) as e:
      self.fetcher.fetch('http://foo',
                         self.listener,
                         chunk_size_bytes=1024,
                         timeout_secs=60)

      self.assertEqual(404, e.exception.response_code)
      self.requests.get.expect_called_once_with('http://foo', allow_redirects=True, stream=True,
                                                timeout=60)
      self.listener.status.expect_called_once_with(404)
      self.response.close.expect_called_once_with()

  def test_iter_content_error(self):
    self.requests.get.return_value = self.response
    self.response.status_code = 200
    self.response.headers = {}
    self.response.iter_content.side_effect = requests.Timeout

    with self.assertRaises(self.fetcher.TransientError):
      self.fetcher.fetch('http://foo',
                         self.listener,
                         chunk_size_bytes=1024,
                         timeout_secs=60)

      self.requests.get.expect_called_once_with('http://foo', allow_redirects=True, stream=True,
                                                timeout=60)
      self.response.iter_content.expect_called_once_with(chunk_size=1024)
      self.listener.status.expect_called_once_with(200, content_length=None)
      self.response.close.expect_called_once_with()

  def expect_download(self, path_or_fd=None):
    with self.expect_get('http://1',
                         chunk_size_bytes=13,
                         timeout_secs=13,
                         listener=False) as (chunks, expected_listener_calls):

      path = self.fetcher.download('http://1',
                                   path_or_fd=path_or_fd,
                                   chunk_size_bytes=13,
                                   timeout_secs=13)

      self.response.close.expect_called_once_with()
      downloaded = self.concat_chunks(chunks)
      return downloaded, path

  def test_download(self):
    downloaded, path = self.expect_download()
    try:
      with open(path, 'rb') as fp:
        self.assertEqual(downloaded, fp.read())
    finally:
      os.unlink(path)

  def test_download_fd(self):
    with temporary_file() as fd:
      downloaded, path = self.expect_download(path_or_fd=fd)
      self.assertEqual(path, fd.name)
      fd.close()
      with open(path, 'rb') as fp:
        self.assertEqual(downloaded, fp.read())

  def test_download_path(self):
    with temporary_file() as fd:
      fd.close()
      downloaded, path = self.expect_download(path_or_fd=fd.name)
      self.assertEqual(path, fd.name)
      with open(path, 'rb') as fp:
        self.assertEqual(downloaded, fp.read())

  @mock.patch('time.time')
  def test_progress_listener(self, timer):
    timer.side_effect = [0, 1.137]

    stream = BytesIO()
    progress_listener = Fetcher.ProgressListener(width=5, chunk_size_bytes=1, stream=stream)

    with self.expect_get('http://baz',
                         chunk_size_bytes=1,
                         timeout_secs=37,
                         chunks=[[1]] * 1024) as (chunks, expected_listener_calls):

      self.fetcher.fetch('http://baz',
                         progress_listener.wrap(self.listener),
                         chunk_size_bytes=1,
                         timeout_secs=37)

    self.assert_listener_calls(expected_listener_calls, chunks)

    # We just test the last progress line which should indicate a 100% complete download.
    # We control progress bar width (5 dots), size (1KB) and total time downloading (fake 1.137s).
    self.assertEqual('100% ..... 1 KB 1.137s\n', stream.getvalue().decode('utf-8').split('\r')[-1])


class FetcherRedirectTest(unittest.TestCase):
  # NB(Eric Ayers): Using class variables like this seems horrible, but I can't figure out a better
  # to pass state between the test and the RedirectHTTPHandler class because it gets
  # re-instantiated on every request.
  _URL = None
  _URL2_ACCESSED = False
  _URL1_ACCESSED = False

  # A trivial HTTP server that serves up a redirect from /url2 --> /url1 and some hard-coded
  # responses in the HTTP message body.
  class RedirectHTTPHandler(http.server.BaseHTTPRequestHandler):

    def __init__(self, request, client_address, server):
      # The base class implements GET and HEAD.
      # Old-style class, so we must invoke __init__ this way.
      http.server.BaseHTTPRequestHandler.__init__(self, request, client_address, server)

    def do_GET(self):
      if self.path.endswith('url2'):
        self.send_response(302)
        redirect_url = '{}/url1'.format(FetcherRedirectTest._URL)
        self.send_header('Location',redirect_url)
        self.end_headers()
        self.wfile.write('redirecting you to {}'.format(redirect_url).encode('utf-8'))
        FetcherRedirectTest._URL2_ACCESSED = True
      elif self.path.endswith('url1'):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'returned from redirect')
        FetcherRedirectTest._URL1_ACCESSED = True
      else:
        self.send_response(404)
      self.end_headers()

  @contextmanager
  def setup_server(self):
    httpd = None
    httpd_thread = None
    try:
      handler = self.RedirectHTTPHandler
      httpd = socketserver.TCPServer(('localhost', 0), handler)
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

    fetcher = Fetcher('/unused/root/dir')
    with self.setup_server() as base_url:
      self._URL = base_url
      self.assertFalse(self._URL2_ACCESSED)
      self.assertFalse(self._URL1_ACCESSED)

      path = fetcher.download(base_url + '/url2')
      self.assertTrue(self._URL2_ACCESSED)
      self.assertTrue(self._URL1_ACCESSED)

      with open(path) as fp:
        self.assertIn(fp.read(), ['returned from redirect\n', 'returned from redirect\r\n'])
