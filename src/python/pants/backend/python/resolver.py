# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pex.crawler import Crawler
from pex.fetcher import Fetcher, PyPIFetcher
from pex.http import Context
from pex.interpreter import PythonInterpreter
from pex.iterator import Iterator
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


def context_from_config(config):
  # TODO(wickman) Add retry, conn_timeout, threads, etc configuration here.
  return Context.get()


def resolve_multi(config,
                  requirements,
                  interpreter=None,
                  platforms=None,
                  ttl=3600,
                  find_links=None):
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
     :param ttl: Time in seconds before we consider re-resolving an open-ended requirement, e.g.
                 "flask>=0.2" if a matching distribution is available on disk.  Defaults
                 to 3600.
     :param find_links: Additional paths to search for source packages during resolution.
  """
  distributions = dict()
  interpreter = interpreter or PythonInterpreter.get()
  if not isinstance(interpreter, PythonInterpreter):
    raise TypeError('Expected interpreter to be a PythonInterpreter, got %s' % type(interpreter))

  cache = PythonSetup(config).scratch_dir('install_cache', default_name='eggs')
  platforms = get_platforms(platforms or config.getlist('python-setup', 'platforms', ['current']))
  fetchers = fetchers_from_config(config)
  if find_links:
    fetchers.extend(Fetcher([path]) for path in find_links)
  context = context_from_config(config)

  for platform in platforms:
    distributions[platform] = resolve(
        requirements=requirements,
        interpreter=interpreter,
        fetchers=fetchers,
        platform=platform,
        context=context,
        cache=cache,
        cache_ttl=ttl)

  return distributions
