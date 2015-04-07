# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.fetcher import Fetcher
from pex.interpreter import PythonInterpreter
from pex.platforms import Platform
from pex.resolver import resolve


def get_platforms(platform_list):
  def translate(platform):
    return Platform.current() if platform == 'current' else platform
  return tuple(set(map(translate, platform_list)))



def resolve_multi(python_setup,
                  python_repos,
                  requirements,
                  interpreter=None,
                  platforms=None,
                  ttl=3600,
                  find_links=None):
  """Multi-platform dependency resolution for PEX files.

     Given a pants configuration and a set of requirements, return a list of distributions
     that must be included in order to satisfy them.  That may involve distributions for
     multiple platforms.

     :param python_setup: Pants :class:`PythonSetup` object.
     :param python_repos: Pants :class:`PythonRepos` object.
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
    raise TypeError('Expected interpreter to be a PythonInterpreter, got {}'.format(type(interpreter)))

  cache = os.path.join(python_setup.scratch_dir, 'eggs')
  platforms = get_platforms(platforms or python_setup.platforms)
  fetchers = python_repos.get_fetchers()
  if find_links:
    fetchers.extend(Fetcher([path]) for path in find_links)
  context = python_repos.get_network_context()

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
