# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pex.fetcher import Fetcher, PyPIFetcher
from pex.http import Crawler
from pex.interpreter import PythonInterpreter
from pex.obtainer import CachingObtainer
from pex.platforms import Platform
from pex.resolver import resolve
from pex.translator import Translator

from pants.backend.python.python_setup import PythonSetup


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
      obtainer = CachingObtainer(
          install_cache=self.install_cache,
          ttl=self.ttl,
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
