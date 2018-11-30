# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import time

import requests
import responses
from future.moves.urllib.parse import urlparse
from requests import RequestException

from pants.cache.pinger import BestUrlSelector, InvalidRESTfulCacheProtoError, Pinger
from pants_test.test_base import TestBase


class TestPinger(TestBase):

  fast_url = 'http://fast_url'
  slow_url = 'http://slow_url'
  unreachable_url = 'http://unreachable_url'

  latency_by_url = {
    fast_url: 0.1,
    slow_url: 0.3,
    unreachable_url: Pinger.UNREACHABLE
  }

  @classmethod
  def expect_response(cls, url, timeout):
    latency = cls.latency_by_url[url]
    body = requests.exceptions.ConnectTimeout() if latency >= timeout else ''

    def callback(_):
      if latency < timeout:
        time.sleep(latency)
      return 200, {}, body

    responses.add_callback(responses.HEAD, url, callback)

  @classmethod
  def pinger(cls, timeout, urls, tries=2):
    for url in urls:
      for _ in range(tries):
        cls.expect_response(url, timeout)

    return Pinger(timeout=timeout, tries=tries)

  @responses.activate
  def test_pinger_times_correct(self):
    urls = [self.fast_url, self.slow_url, self.unreachable_url]
    test = self.pinger(timeout=0.4, urls=urls)
    ping_results = dict(test.pings(urls))
    self.assertNotEqual(ping_results[self.slow_url], Pinger.UNREACHABLE)
    self.assertLess(ping_results[self.fast_url], ping_results[self.slow_url])
    self.assertEqual(ping_results[self.unreachable_url], Pinger.UNREACHABLE)

  @responses.activate
  def test_pinger_timeout_config(self):
    urls = [self.fast_url, self.slow_url]
    test = self.pinger(timeout=0.2, urls=urls)
    ping_results = dict(test.pings(urls))
    self.assertLess(ping_results[self.fast_url], 2)
    self.assertEqual(ping_results[self.slow_url], Pinger.UNREACHABLE)

  @responses.activate
  def test_global_pinger_memo(self):
    urls = [self.slow_url]
    fast_pinger = self.pinger(timeout=0.2, urls=urls)
    slow_pinger = self.pinger(timeout=0.4, urls=urls)
    self.assertEqual(fast_pinger.pings([self.slow_url])[0][1], Pinger.UNREACHABLE)
    self.assertNotEqual(slow_pinger.pings([self.slow_url])[0][1], Pinger.UNREACHABLE)

  def test_https_external_pinger(self):
    # NB(gmalmquist): I spent quite some time trying to spin up an HTTPS server and get it to work
    # with this test, but it appears to be more trouble than it's worth. If you're feeling
    # ambitious, feel free to give it a try.
    pinger = Pinger(timeout=5, tries=2)
    self.assertLess(pinger.ping('https://github.com'), Pinger.UNREACHABLE)


class TestBestUrlSelector(TestBase):

  def setUp(self):
    self.url1 = 'http://host1:123'
    self.url2 = 'https://host2:456'
    self.unsupported_url = 'ftp://ftpserver'
    self.best_url_selector = BestUrlSelector([self.url1, self.url2], max_failures=1)

  def call_url(self, expected_url, with_error=False):
    try:
      with self.best_url_selector.select_best_url() as url:
        self.assertEqual(urlparse(expected_url), url)

        if with_error:
          raise RequestException('error connecting to {}'.format(url))
    except RequestException:
      pass

  def test_unsupported_protocol(self):
    with self.assertRaises(InvalidRESTfulCacheProtoError):
      BestUrlSelector([self.unsupported_url])

  def test_select_next_url_after_max_consecutive_failures(self):
    self.call_url(self.url1, with_error=True)

    # A success call will reset the counter.
    self.call_url(self.url1)

    # Too many failures for url1, switch to url2.
    self.call_url(self.url1, with_error=True)
    self.call_url(self.url1, with_error=True)
    self.call_url(self.url2)

    # Too many failures for url2, switch to url1.
    self.call_url(self.url2, with_error=True)
    self.call_url(self.url2, with_error=True)
    self.call_url(self.url1)
