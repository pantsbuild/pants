from __future__ import print_function

import os
import time

from twitter.common.dirutil import touch
from twitter.common.python.base import requirement_is_exact
from twitter.common.python.fetcher import Fetcher, PyPIFetcher
from twitter.common.python.http import Crawler
from twitter.common.python.obtainer import Obtainer, CachingObtainer
from twitter.common.python.interpreter import PythonInterpreter
from twitter.common.python.package import distribution_compatible
from twitter.common.python.platforms import Platform
from twitter.common.python.resolver import resolve
from twitter.common.python.translator import (
    ChainedTranslator,
    EggTranslator,
    SourceTranslator,
    Translator
)

from .python_setup import PythonSetup

from pkg_resources import (
    Environment,
    WorkingSet,
)


def get_platforms(platform_list):
  def translate(platform):
    return Platform.current() if platform == 'current' else platform
  return tuple(set(map(translate, platform_list)))


def fetchers_from_config(config):
  fetchers = []
  fetchers.extend(Fetcher([url]) for url in config.getlist('python-repos', 'repos', []))
  fetchers.extend(PyPIFetcher(url) for url in config.getlist('python-repos', 'indices', []))
  return fetchers


def crawler_from_config(config, conn_timeout=None):
  download_cache = PythonSetup(config).scratch_dir('download_cache', default_name='downloads')
  return Crawler(cache=download_cache, conn_timeout=conn_timeout)


class PantsObtainer(CachingObtainer):
  def iter(self, requirement):
    if hasattr(requirement, 'repository') and requirement.repository:
      obtainer = Obtainer(
          crawler=self._crawler,
          fetchers=[Fetcher([requirement.repository])],
          translators=self._translator)
      for package in obtainer.iter(requirement):
        yield package
    else:
      for package in super(PantsObtainer, self).iter(requirement):
        yield package


def resolve_multi(config,
                  requirements,
                  interpreter=None,
                  platforms=None,
                  conn_timeout=None,
                  ttl=3600):
  """Multi-platform dependency resolution for PEX files.

     Given a pants configuration and a set of requirements, return a list of distributions
     that must be included in order to satisfy them.  That may involve distributions for
     multiple platforms.

     :param config: Pants :class:`Config` object.
     :param requirements: A list of :class:`PythonRequirement` objects to resolve.
     :param interpreter: :class:`PythonInterpreter` for which requirements should be resolved.
                         If None specified, defaults to current interpreter.
     :param platforms: Optional list of platforms against requirements will be resolved. If
                         None specified, the defaults from `config` will be used.
     :param conn_timeout: Optional connection timeout for any remote fetching.
     :param ttl: Time in seconds before we consider re-resolving an open-ended requirement, e.g.
                 "flask>=0.2" if a matching distribution is available on disk.  Defaults
                 to 3600.
  """
  distributions = dict()
  interpreter = interpreter or PythonInterpreter.get()
  if not isinstance(interpreter, PythonInterpreter):
    raise TypeError('Expected interpreter to be a PythonInterpreter, got %s' % type(interpreter))

  install_cache = PythonSetup(config).scratch_dir('install_cache', default_name='eggs')
  platforms = get_platforms(platforms or config.getlist('python-setup', 'platforms', ['current']))

  for platform in platforms:
    translator = Translator.default(
        install_cache=install_cache,
        interpreter=interpreter,
        platform=platform,
        conn_timeout=conn_timeout)

    obtainer = PantsObtainer(
        install_cache=install_cache,
        crawler=crawler_from_config(config, conn_timeout=conn_timeout),
        fetchers=fetchers_from_config(config) or [PyPIFetcher()],
        translators=translator)

    distributions[platform] = resolve(requirements=requirements,
                                      obtainer=obtainer,
                                      interpreter=interpreter,
                                      platform=platform)

  return distributions
