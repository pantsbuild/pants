# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from six.moves import urllib

from pants.java.distribution.distribution import DistributionLocator
from pants.subsystem.subsystem import Subsystem


class IvySubsystem(Subsystem):
  """Common configuration items for ivy tasks."""
  options_scope = 'ivy'

  _DEFAULT_VERSION = '2.3.0'
  _DEFAULT_URL = ('https://repo1.maven.org/maven2/'
                  'org/apache/ivy/ivy/'
                  '{version}/ivy-{version}.jar'.format(version=_DEFAULT_VERSION))

  @classmethod
  def register_options(cls, register):
    super(IvySubsystem, cls).register_options(register)
    register('--http-proxy', advanced=True,
             help='Specify a proxy URL for http requests.')
    register('--https-proxy', advanced=True,
             help='Specify a proxy URL for https requests.')
    register('--bootstrap-jar-url', advanced=True, default=cls._DEFAULT_URL,
             help='Location to download a bootstrap version of Ivy.')
    register('--bootstrap-fetch-timeout-secs', type=int, advanced=True, default=10,
             help='Timeout the fetch if the connection is idle for longer than this value.')
    register('--ivy-profile', advanced=True, default=cls._DEFAULT_VERSION,
             help='The version of ivy to fetch.')
    register('--cache-dir', advanced=True, default=os.path.expanduser('~/.ivy2/pants'),
             help='Directory to store artifacts retrieved by Ivy.')
    register('--ivy-settings', advanced=True,
             help='Location of XML configuration file for Ivy settings.')

  @classmethod
  def subsystem_dependencies(cls):
    return super(IvySubsystem, cls).subsystem_dependencies() + (DistributionLocator,)

  def http_proxy(self):
    """Set ivy to use an http proxy.

    Expects a string of the form http://<host>:<port>
    """
    if os.getenv('HTTP_PROXY'):
      return os.getenv('HTTP_PROXY')
    if os.getenv('http_proxy'):
      return os.getenv('http_proxy')
    return self.get_options().http_proxy

  def https_proxy(self):
    """Set ivy to use an https proxy.

    Expects a string of the form http://<host>:<port>
    """
    if os.getenv('HTTPS_PROXY'):
      return os.getenv('HTTPS_PROXY')
    if os.getenv('https_proxy'):
      return os.getenv('https_proxy')
    return self.get_options().https_proxy

  def extra_jvm_options(self):
    extra_options = []
    http_proxy = self.http_proxy()
    if http_proxy:
      host, port = self._parse_proxy_string(http_proxy)
      extra_options.extend([
        "-Dhttp.proxyHost={}".format(host),
        "-Dhttp.proxyPort={}".format(port),
        ])

    https_proxy = self.https_proxy()
    if https_proxy:
      host, port = self._parse_proxy_string(https_proxy)
      extra_options.extend([
        "-Dhttps.proxyHost={}".format(host),
        "-Dhttps.proxyPort={}".format(port),
        ])
    return extra_options

  def _parse_proxy_string(self, proxy_string):
    parse_result = urllib.parse.urlparse(proxy_string)
    return parse_result.hostname, parse_result.port
