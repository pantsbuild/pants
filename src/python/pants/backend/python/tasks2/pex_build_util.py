# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.fetcher import Fetcher
from pex.platforms import Platform
from pex.resolver import resolve
from twitter.common.collections import OrderedSet

from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.resources import Resources
from pants.python.python_repos import PythonRepos


def has_python_sources(tgt):
  # We'd like to take all PythonTarget subclasses, but currently PythonThriftLibrary and
  # PythonAntlrLibrary extend PythonTarget, and until we fix that (which we can't do until
  # we remove the old python pipeline entirely) we want to ignore those target types here.
  return isinstance(tgt, (PythonLibrary, PythonTests, PythonBinary, Resources))


def has_resources(tgt):
  return isinstance(tgt, Resources)


def has_python_requirements(tgt):
  return isinstance(tgt, PythonRequirementLibrary)


def dump_sources(builder, tgt, log):
  buildroot = get_buildroot()
  log.debug('  Dumping sources: {}'.format(tgt))
  for relpath in tgt.sources_relative_to_source_root():
    try:
      src = os.path.join(buildroot, tgt.target_base, relpath)
      if isinstance(tgt, Resources):
        builder.add_resource(src, relpath)
      else:
        builder.add_source(src, relpath)
    except OSError:
      log.error('Failed to copy {} for target {}'.format(
        os.path.join(tgt.target_base, relpath), tgt.address.spec))
      raise

  if (getattr(tgt, '_resource_target_specs', None) or
      getattr(tgt, '_synthetic_resources_target', None)):
    # No one should be on old-style resources any more.  And if they are,
    # switching to the new python pipeline will be a great opportunity to fix that.
    raise TaskError('Old-style resources not supported for target {}.  '
                    'Depend on resources() targets instead.'.format(tgt.address.spec))


def dump_requirements(builder, interpreter, req_libs, log, platforms=None):
  """Multi-platform dependency resolution for PEX files.

  Returns a list of distributions that must be included in order to satisfy a set of requirements.
  That may involve distributions for multiple platforms.

  :param builder: Dump the requirements into this builder.
  :param interpreter: The :class:`PythonInterpreter` to resolve requirements for.
  :param req_libs: A list of :class:`PythonRequirementLibrary` targets to resolve.
  :param log: Use this logger.
  :param platforms: A list of :class:`Platform`s to resolve requirements for.
                    Defaults to the platforms specified by PythonSetup.
  """

  # Gather and de-dup all requirements.
  reqs = OrderedSet()
  for req_lib in req_libs:
    for req in req_lib.requirements:
      reqs.add(req)

  # See which ones we need to build.
  reqs_to_build = OrderedSet()
  find_links = OrderedSet()
  for req in reqs:
    # TODO: should_build appears to be hardwired to always be True. Get rid of it?
    if req.should_build(interpreter.python, Platform.current()):
      reqs_to_build.add(req)
      log.debug('  Dumping requirement: {}'.format(req))
      builder.add_requirement(req.requirement)
      if req.repository:
        find_links.add(req.repository)
    else:
      log.debug('  Skipping {} based on version filter'.format(req))

  # Resolve the requirements into distributions.
  distributions = _resolve_multi(interpreter, reqs_to_build, platforms, find_links)

  locations = set()
  for platform, dists in distributions.items():
    for dist in dists:
      if dist.location not in locations:
        log.debug('  Dumping distribution: .../{}'.format(os.path.basename(dist.location)))
        builder.add_distribution(dist)
      locations.add(dist.location)


def _resolve_multi(interpreter, requirements, platforms, find_links):
  """Multi-platform dependency resolution for PEX files.

  Returns a list of distributions that must be included in order to satisfy a set of requirements.
  That may involve distributions for multiple platforms.

  :param interpreter: The :class:`PythonInterpreter` to resolve for.
  :param requirements: A list of :class:`PythonRequirement` objects to resolve.
  :param platforms: A list of :class:`Platform`s to resolve for.
  :param find_links: Additional paths to search for source packages during resolution.
  :return: Map of platform name -> list of :class:`pkg_resources.Distribution` instances needed
           to satisfy the requirements on that platform.
  """
  python_setup = PythonSetup.global_instance()
  python_repos = PythonRepos.global_instance()
  platforms = platforms or python_setup.platforms
  find_links = find_links or []
  distributions = {}
  fetchers = python_repos.get_fetchers()
  fetchers.extend(Fetcher([path]) for path in find_links)

  for platform in platforms:
    requirements_cache_dir = os.path.join(python_setup.resolver_cache_dir,
                                          str(interpreter.identity))
    distributions[platform] = resolve(
      requirements=[req.requirement for req in requirements],
      interpreter=interpreter,
      fetchers=fetchers,
      platform=None if platform == 'current' else platform,
      context=python_repos.get_network_context(),
      cache=requirements_cache_dir,
      cache_ttl=python_setup.resolver_cache_ttl,
      allow_prereleases=python_setup.resolver_allow_prereleases)

  return distributions
