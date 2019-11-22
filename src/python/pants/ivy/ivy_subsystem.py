# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import urllib

from pants.binaries.binary_tool import Script
from pants.binaries.binary_util import BinaryToolUrlGenerator
from pants.java.distribution.distribution import DistributionLocator


class IvySubsystem(Script):
  """Common configuration items for ivy tasks.

  :API: public
  """
  options_scope = 'ivy'
  default_version = '2.4.0'

  _default_urls = [
      'https://repo1.maven.org/maven2/org/apache/ivy/ivy/{version}/ivy-{version}.jar',
      'https://maven-central.storage-download.googleapis.com/repos/central/data/org/apache/ivy/ivy/{version}/ivy-{version}.jar',
    ]

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--http-proxy', advanced=True,
             help='Specify a proxy URL for http requests.')
    register('--https-proxy', advanced=True,
             help='Specify a proxy URL for https requests.')
    register('--bootstrap-jar-url', advanced=True, default=cls._default_urls[0],
             removal_version='1.25.0.dev1', removal_hint='Use --bootstrap-jar-urls',
             help='Location to download a bootstrap version of Ivy.')
    register('--bootstrap-jar-urls', advanced=True, type=list, default=cls._default_urls,
             help='List of URLs with templated {version}s to use to download a bootstrap copy of Ivy.')
    register('--bootstrap-fetch-timeout-secs', type=int, advanced=True, default=10,
             removal_version='1.25.0.dev1', removal_hint='Use --binaries-fetch-timeout-secs.',
             help='Timeout the fetch if the connection is idle for longer than this value.')
    register('--ivy-profile', advanced=True, default=None,
             help='An ivy.xml file.')
    register('--cache-dir', advanced=True, default=os.path.expanduser('~/.ivy2/pants'),
             help='The default directory used for both the Ivy resolution and repository caches.'
                  'If you want to isolate the resolution cache from the repository cache, we '
                  'recommend setting both the --resolution-cache-dir and --repository-cache-dir '
                  'instead of using --cache-dir')
    register('--resolution-cache-dir', advanced=True,
             help='Directory to store Ivy resolution artifacts.')
    register('--repository-cache-dir', advanced=True,
             help='Directory to store Ivy repository artifacts.')
    register('--ivy-settings', advanced=True,
             help='Location of XML configuration file for Ivy settings.')
    register('--bootstrap-ivy-settings', advanced=True,
             help='Bootstrap Ivy XML configuration file.')

  @classmethod
  def subsystem_dependencies(cls):
    return super().subsystem_dependencies() + (DistributionLocator,)

  def get_external_url_generator(self):
    # NB: Remove with deprecation.
    if self.get_options().is_flagged('bootstrap_jar_url'):
      urls = [self.get_options().bootstrap_jar_url]
    else:
      urls = list(self.get_options().bootstrap_jar_urls)
    return IvyUrlGenerator(urls)

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

  def resolution_cache_dir(self):
    if self.get_options().resolution_cache_dir:
      return self.get_options().resolution_cache_dir
    else:
      return self.get_options().cache_dir

  def repository_cache_dir(self):
    if self.get_options().repository_cache_dir:
      return self.get_options().repository_cache_dir
    else:
      return self.get_options().cache_dir


class IvyUrlGenerator(BinaryToolUrlGenerator):

  def __init__(self, template_urls):
    super().__init__()
    self._template_urls = template_urls

  def generate_urls(self, version, host_platform):
    return [url.format(version=version) for url in self._template_urls]
