# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import shutil

from pex.fetcher import Fetcher
from pex.interpreter import PythonInterpreter
from pex.pex import PEX
from pex.pex_builder import PEXBuilder
from pex.platforms import Platform
from pex.resolver import resolve
from twitter.common.collections import OrderedSet

from pants.backend.python.python_setup import PythonRepos, PythonSetup
from pants.invalidation.cache_manager import VersionedTargetSet
from pants.task.task import Task
from pants.util.dirutil import safe_rmtree


class ResolveRequirementsTaskBase(Task):
  """Base class for tasks that resolve 3rd-party Python requirements.

  Creates an (unzipped) PEX on disk containing all the resolved requirements.
  This PEX can be merged with other PEXes to create a unified Python environment
  for running the relevant python code.
  """

  @classmethod
  def subsystem_dependencies(cls):
    return super(ResolveRequirementsTaskBase, cls).subsystem_dependencies() + (PythonSetup, PythonRepos)

  @classmethod
  def prepare(cls, options, round_manager):
    round_manager.require_data(PythonInterpreter)

  def resolve_requirements(self, req_libs):
    with self.invalidated(req_libs) as invalidation_check:
      # If there are no relevant targets, we still go through the motions of resolving
      # an empty set of requirements, to prevent downstream tasks from having to check
      # for this special case.
      if invalidation_check.all_vts:
        target_set_id = VersionedTargetSet.from_versioned_targets(
            invalidation_check.all_vts).cache_key.hash
      else:
        target_set_id = 'no_targets'

      interpreter = self.context.products.get_data(PythonInterpreter)
      path = os.path.join(self.workdir, str(interpreter.identity), target_set_id)

      # Note that we check for the existence of the directory, instead of for invalid_vts, to cover the empty case.
      if not os.path.isdir(path):
        path_tmp = path + '.tmp'
        safe_rmtree(path_tmp)
        self._build_pex(interpreter, path_tmp, req_libs)
        safe_rmtree(path)
        shutil.move(path_tmp, path)

    return PEX(os.path.realpath(path), interpreter=interpreter)

  def _build_pex(self, interpreter, path, req_libs):
    builder = PEXBuilder(path=path, interpreter=interpreter, copy=True)

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
        self.context.log.debug('  Dumping requirement: {}'.format(req))
        builder.add_requirement(req.requirement)
        if req.repository:
          find_links.add(req.repository)
      else:
        self.context.log.debug('  Skipping {} based on version filter'.format(req))

    # Resolve the requirements into distributions.
    distributions = self._resolve_multi(interpreter, reqs_to_build, find_links)

    locations = set()
    for platform, dists in distributions.items():
      for dist in dists:
        if dist.location not in locations:
          self.context.log.debug('  Dumping distribution: .../{}'.format(
              os.path.basename(dist.location)))
          builder.add_distribution(dist)
        locations.add(dist.location)

    builder.freeze()

  def _resolve_multi(self, interpreter, requirements, find_links):
    """Multi-platform dependency resolution for PEX files.

    Returns a list of distributions that must be included in order to satisfy a set of requirements.
    That may involve distributions for multiple platforms.

    :param interpreter: The :class:`PythonInterpreter` to resolve for.
    :param requirements: A list of :class:`PythonRequirement` objects to resolve.
    :param find_links: Additional paths to search for source packages during resolution.
    :return: Map of platform name -> list of :class:`pkg_resources.Distribution` instances needed
             to satisfy the requirements on that platform.
    """
    python_setup = PythonSetup.global_instance()
    python_repos = PythonRepos.global_instance()
    distributions = {}
    fetchers = python_repos.get_fetchers()
    fetchers.extend(Fetcher([path]) for path in find_links)

    for platform in python_setup.platforms:
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
