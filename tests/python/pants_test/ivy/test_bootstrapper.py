# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.ivy.bootstrapper import Bootstrapper
from pants.util.contextutil import environment_as
from pants_test.base_test import BaseTest


class BootstrapperTest(BaseTest):

  def test_parse_proxy_string(self):
    bootstrapper = Bootstrapper().instance()

    self.assertEquals(('example.com', 1234),
                      bootstrapper._parse_proxy_string('http://example.com:1234'))
    self.assertEquals(('secure-example.com', 999),
                      bootstrapper._parse_proxy_string('http://secure-example.com:999'))
    # trailing slash is ok
    self.assertEquals(('example.com', 1234),
                      bootstrapper._parse_proxy_string('http://example.com:1234/'))

  def test_proxy_from_env(self):
    bootstrapper = Bootstrapper().instance()

    self.assertIsNone(bootstrapper._http_proxy())
    self.assertIsNone(bootstrapper._https_proxy())

    with environment_as(HTTP_PROXY='http://proxy.example.com:456',
                        HTTPS_PROXY='https://secure-proxy.example.com:789'):
      self.assertEquals('http://proxy.example.com:456', bootstrapper._http_proxy())
      self.assertEquals('https://secure-proxy.example.com:789', bootstrapper._https_proxy())

      self.assertEquals([
        '-Dhttp.proxyHost=proxy.example.com',
        '-Dhttp.proxyPort=456',
        '-Dhttps.proxyHost=secure-proxy.example.com',
        '-Dhttps.proxyPort=789',
      ], bootstrapper._extra_jvm_options())
