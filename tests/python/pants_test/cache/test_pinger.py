# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest
import urlparse

from requests import RequestException

from pants.cache.pinger import BestUrlSelector, InvalidRESTfulCacheProtoError, Pinger
from pants_test.base_test import BaseTest
from pants_test.cache.delay_server import setup_delayed_server


class TestPinger(BaseTest):
  # NB(gmalmquist): The tests in this file pass locally, but are decorated with expectedFailure
  # because CI is usually too slow to run them before they timeout.

  resolution = 1
  fast_delay_seconds = 0
  fast_timeout_seconds = fast_delay_seconds + resolution
  slow_delay_seconds = fast_timeout_seconds + resolution
  slow_timeout_seconds = slow_delay_seconds + resolution
  unreachable_delay_seconds = slow_timeout_seconds + 10 * resolution
  message = "This test may fail occasionally if the CPU is very busy."

  def setUp(self):
    unreachable = setup_delayed_server(self.unreachable_delay_seconds)
    slow = setup_delayed_server(self.slow_delay_seconds)
    fast = setup_delayed_server(self.fast_delay_seconds)
    self.servers = [unreachable, slow, fast]
    self.fast_netloc = 'http://localhost:{}'.format(fast.socket.getsockname()[1])
    self.slow_netloc = 'http://localhost:{}'.format(slow.socket.getsockname()[1])
    self.unreachable_netloc = 'http://localhost:{}'.format(unreachable.socket.getsockname()[1])
    self.https_external_netlock = 'https://github.com'

  @unittest.expectedFailure
  def test_pinger_times_correct(self):
    test = Pinger(timeout=self.slow_timeout_seconds, tries=2)
    netlocs = [self.fast_netloc, self.slow_netloc, self.unreachable_netloc]
    ping_results = dict(test.pings(netlocs))
    self.assertNotEqual(ping_results[self.slow_netloc], Pinger.UNREACHABLE)
    self.assertLess(ping_results[self.fast_netloc], ping_results[self.slow_netloc])
    self.assertEqual(ping_results[self.unreachable_netloc], Pinger.UNREACHABLE, msg=self.message)

  @unittest.expectedFailure
  def test_pinger_timeout_config(self):
    test = Pinger(timeout=self.fast_timeout_seconds, tries=2)
    netlocs = [self.fast_netloc, self.slow_netloc]
    ping_results = dict(test.pings(netlocs))
    self.assertLess(ping_results[self.fast_netloc], self.fast_timeout_seconds)
    self.assertEqual(
      ping_results[self.slow_netloc], Pinger.UNREACHABLE, msg=self.message)

  @unittest.expectedFailure
  def test_global_pinger_memo(self):
    fast_pinger = Pinger(timeout=self.fast_timeout_seconds, tries=2)
    slow_pinger = Pinger(timeout=self.slow_timeout_seconds, tries=2)
    self.assertEqual(
      fast_pinger.pings([self.slow_netloc])[0][1], Pinger.UNREACHABLE, msg=self.message)
    self.assertNotEqual(
      slow_pinger.pings([self.slow_netloc])[0][1], Pinger.UNREACHABLE, msg=self.message)

  @unittest.expectedFailure
  def test_https_external_pinger(self):
    # NB(gmalmquist): I spent quite some time trying to spin up an HTTPS server and get it to work
    # with this test, but it appears to be more trouble than it's worth. If you're feeling
    # ambitious, feel free to give it a try.
    pinger = Pinger(timeout=self.slow_delay_seconds, tries=2)
    self.assertLess(pinger.ping(self.https_external_netlock), Pinger.UNREACHABLE)

  def tearDown(self):
    for server in self.servers:
      server.shutdown()


class TestBestUrlSelector(BaseTest):

  def setUp(self):
    self.url1 = 'http://host1:123'
    self.url2 = 'https://host2:456'
    self.unsupported_url = 'ftp://ftpserver'
    self.best_url_selector = BestUrlSelector([self.url1, self.url2], max_failures=1)

  def call_url(self, expected_url, with_error=False):
    try:
      with self.best_url_selector.select_best_url() as url:
        self.assertEquals(urlparse.urlparse(expected_url), url)

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
