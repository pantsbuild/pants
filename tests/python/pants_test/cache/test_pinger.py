# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.cache.pinger import Pinger
from pants_test.base_test import BaseTest
from pants_test.cache.delay_server import setup_delayed_server


def get_delayed_handler(delay):
  class DelayResponseHandler(SimpleHTTPServer.SimpleHTTPRequestHandler):
    def do_HEAD(self):
      time.sleep(delay)
      self.send_response(200)
      self.end_headers()

  return DelayResponseHandler


class TestPinger(BaseTest):
  timeout_seconds = .6
  slow_seconds = .05
  fast_seconds = 0

  def setUp(self):
    timeout = setup_delayed_server(self.timeout_seconds)
    slow = setup_delayed_server(self.slow_seconds)
    fast = setup_delayed_server(self.fast_seconds)
    self.servers = [timeout, slow, fast]
    self.fast_netloc = 'localhost:{}'.format(fast.socket.getsockname()[1])
    self.slow_netloc = 'localhost:{}'.format(slow.socket.getsockname()[1])
    self.timeout_netloc = 'localhost:{}'.format(timeout.socket.getsockname()[1])

  def test_pinger_times_correct(self):
    test = Pinger(timeout=.5, tries=2)
    netlocs = [self.fast_netloc, self.slow_netloc, self.timeout_netloc]
    ping_results = dict(test.pings(netlocs))
    self.assertLess(ping_results[self.fast_netloc], ping_results[self.slow_netloc])
    self.assertEqual(ping_results[self.timeout_netloc], Pinger.UNREACHABLE)

  def test_pinger_timeout_config(self):
    test = Pinger(timeout=self.slow_seconds - .01, tries=2)
    netlocs = [self.fast_netloc, self.slow_netloc]
    ping_results = dict(test.pings(netlocs))
    self.assertLess(ping_results[self.fast_netloc], 1)
    self.assertEqual(ping_results[self.slow_netloc], Pinger.UNREACHABLE)

  def test_global_pinger_memo(self):
    fast_pinger = Pinger(timeout=self.slow_seconds - .01, tries=2)
    slow_pinger = Pinger(timeout=self.timeout_seconds, tries=2)
    self.assertEqual(fast_pinger.pings([self.slow_netloc])[0][1], Pinger.UNREACHABLE)
    self.assertNotEqual(slow_pinger.pings([self.slow_netloc])[0][1], Pinger.UNREACHABLE)

  def tearDown(self):
    for server in self.servers:
      server.shutdown()
