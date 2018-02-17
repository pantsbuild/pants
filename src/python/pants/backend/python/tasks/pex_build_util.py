# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pex.fetcher import Fetcher
from pex.resolver import resolve
from twitter.common.collections import OrderedSet

from pants.backend.python.subsystems.python_setup import PythonSetup
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_distribution import PythonDistribution
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.build_graph.files import Files
from pants.python.python_repos import PythonRepos


def is_python_target(tgt):
  # We'd like to take all PythonTarget subclasses, but currently PythonThriftLibrary and
  # PythonAntlrLibrary extend PythonTarget, and until we fix that (which we can't do until
  # we remove the old python pipeline entirely) we want to ignore those target types here.
  return isinstance(tgt, (PythonLibrary, PythonTests, PythonBinary))


def has_python_sources(tgt):
  return is_python_target(tgt) and tgt.has_sources()


def is_local_python_dist(tgt):
  return isinstance(tgt, PythonDistribution)


def has_resources(tgt):
  return isinstance(tgt, Files) and tgt.has_sources()


def has_python_requirements(tgt):
  return isinstance(tgt, PythonRequirementLibrary)


def _create_source_dumper(builder, tgt):
  if type(tgt) == Files:
    # Loose `Files` as opposed to `Resources` or `PythonTarget`s have no (implied) package structure
    # and so we chroot them relative to the build root so that they can be accessed via the normal
    # python filesystem APIs just as they would be accessed outside the chrooted environment.
    # NB: This requires we mark the pex as not zip safe so these `Files` can still be accessed in
    # the context of a built pex distribution.
    chroot_path = lambda relpath: relpath
    builder.info.zip_safe = False
  else:
    chroot_path = lambda relpath: os.path.relpath(relpath, tgt.target_base)

  dump = builder.add_resource if has_resources(tgt) else builder.add_source
  buildroot = get_buildroot()
  return lambda relpath: dump(os.path.join(buildroot, relpath), chroot_path(relpath))


def dump_sources(builder, tgt, log):
  dump_source = _create_source_dumper(builder, tgt)
  log.debug('  Dumping sources: {}'.format(tgt))
  for relpath in tgt.sources_relative_to_buildroot():
    try:
      dump_source(relpath)
    except OSError:
      log.error('Failed to copy {} for target {}'.format(relpath, tgt.address.spec))
      raise

  if (getattr(tgt, '_resource_target_specs', None) or
      getattr(tgt, '_synthetic_resources_target', None)):
    # No one should be on old-style resources any more.  And if they are,
    # switching to the new python pipeline will be a great opportunity to fix that.
    raise TaskError('Old-style resources not supported for target {}.  '
                    'Depend on resources() targets instead.'.format(tgt.address.spec))


def dump_requirement_libs(builder, interpreter, req_libs, log, platforms=None):
  """Multi-platform dependency resolution for PEX files.

  :param builder: Dump the requirements into this builder.
  :param interpreter: The :class:`PythonInterpreter` to resolve requirements for.
  :param req_libs: A list of :class:`PythonRequirementLibrary` targets to resolve.
  :param log: Use this logger.
  :param platforms: A list of :class:`Platform`s to resolve requirements for.
                    Defaults to the platforms specified by PythonSetup.
  """
  reqs = [req for req_lib in req_libs for req in req_lib.requirements]
  dump_requirements(builder, interpreter, reqs, log, platforms)


def dump_requirements(builder, interpreter, reqs, log, platforms=None):
  """Multi-platform dependency resolution for PEX files.

  :param builder: Dump the requirements into this builder.
  :param interpreter: The :class:`PythonInterpreter` to resolve requirements for.
  :param reqs: A list of :class:`PythonRequirement` to resolve.
  :param log: Use this logger.
  :param platforms: A list of :class:`Platform`s to resolve requirements for.
                    Defaults to the platforms specified by PythonSetup.
  """
  deduped_reqs = OrderedSet(reqs)
  find_links = OrderedSet()
  for req in deduped_reqs:
    log.debug('  Dumping requirement: {}'.format(req))
    builder.add_requirement(req.requirement)
    if req.repository:
      find_links.add(req.repository)

  # Resolve the requirements into distributions.
  distributions = _resolve_multi(interpreter, deduped_reqs, platforms, find_links)
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
