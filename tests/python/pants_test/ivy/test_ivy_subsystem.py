# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import unittest

from pants.ivy.ivy_subsystem import IvySubsystem
from pants.util.contextutil import environment_as
from pants_test.subsystem.subsystem_util import global_subsystem_instance


class IvySubsystemTest(unittest.TestCase):

  def test_parse_proxy_string(self):
    ivy_subsystem = global_subsystem_instance(IvySubsystem)
    self.assertEquals(('example.com', 1234),
                      ivy_subsystem._parse_proxy_string('http://example.com:1234'))
    self.assertEquals(('secure-example.com', 999),
                      ivy_subsystem._parse_proxy_string('http://secure-example.com:999'))
    # trailing slash is ok
    self.assertEquals(('example.com', 1234),
                      ivy_subsystem._parse_proxy_string('http://example.com:1234/'))

  def test_proxy_from_env(self):
    ivy_subsystem = global_subsystem_instance(IvySubsystem)
    self.assertIsNone(ivy_subsystem.http_proxy())
    self.assertIsNone(ivy_subsystem.https_proxy())

    with environment_as(HTTP_PROXY='http://proxy.example.com:456',
                        HTTPS_PROXY='https://secure-proxy.example.com:789'):
      self.assertEquals('http://proxy.example.com:456', ivy_subsystem.http_proxy())
      self.assertEquals('https://secure-proxy.example.com:789', ivy_subsystem.https_proxy())

      self.assertEquals([
        '-Dhttp.proxyHost=proxy.example.com',
        '-Dhttp.proxyPort=456',
        '-Dhttps.proxyHost=secure-proxy.example.com',
        '-Dhttps.proxyPort=789',
      ], ivy_subsystem.extra_jvm_options())
