# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.cache.pinger import Pinger
from pants_test.base_test import BaseTest
from pants_test.cache.delay_server import setup_delayed_server


class TestPinger(BaseTest):
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
    self.fast_netloc = 'localhost:{}'.format(fast.socket.getsockname()[1])
    self.slow_netloc = 'localhost:{}'.format(slow.socket.getsockname()[1])
    self.unreachable_netloc = 'localhost:{}'.format(unreachable.socket.getsockname()[1])

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

  def tearDown(self):
    for server in self.servers:
      server.shutdown()
