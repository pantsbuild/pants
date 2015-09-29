# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import functools
import logging
import os
import shutil
import sys
from collections import defaultdict

from pex.fetcher import Fetcher
from pex.pex import PEX
from pex.platforms import Platform
from pex.resolver import resolve
from twitter.common.collections import OrderedSet

from pants.backend.codegen.targets.python_antlr_library import PythonAntlrLibrary
from pants.backend.codegen.targets.python_thrift_library import PythonThriftLibrary
from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.core.targets.prep_command import PrepCommand
from pants.backend.core.targets.resources import Resources
from pants.backend.python.antlr_builder import PythonAntlrBuilder
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.thrift_builder import PythonThriftBuilder
from pants.base.build_environment import get_buildroot
from pants.invalidation.build_invalidator import BuildInvalidator, CacheKeyGenerator
from pants.util.dirutil import safe_mkdir, safe_mkdtemp, safe_rmtree


logger = logging.getLogger(__name__)


class PythonChroot(object):
  _VALID_DEPENDENCIES = {
    PrepCommand: 'prep',
    PythonLibrary: 'libraries',
    PythonRequirementLibrary: 'reqs',
    PythonBinary: 'binaries',
    PythonThriftLibrary: 'thrifts',
    PythonAntlrLibrary: 'antlrs',
    PythonTests: 'tests',
    Resources: 'resources'
  }

  class InvalidDependencyException(Exception):
    def __init__(self, target):
      Exception.__init__(self, "Not a valid Python dependency! Found: {}".format(target))

  @staticmethod
  def get_platforms(platform_list):
    return tuple({Platform.current() if p == 'current' else p for p in platform_list})

  def __init__(self,
               python_setup,
               python_repos,
               ivy_bootstrapper,
               thrift_binary_factory,
               interpreter,
               builder,
               targets,
               platforms,
               extra_requirements=None,
               log=None):
    self._python_setup = python_setup
    self._python_repos = python_repos
    self._ivy_bootstrapper = ivy_bootstrapper
    self._thrift_binary_factory = thrift_binary_factory

    self._interpreter = interpreter
    self._builder = builder
    self._targets = targets
    self._platforms = platforms
    self._extra_requirements = list(extra_requirements) if extra_requirements else []
    self._logger = log or logger

    # Note: unrelated to the general pants artifact cache.
    self._artifact_cache_root = os.path.join(
      self._python_setup.artifact_cache_dir, str(self._interpreter.identity))
    self._key_generator = CacheKeyGenerator()
    self._build_invalidator = BuildInvalidator(self._artifact_cache_root)

  def delete(self):
    """Deletes this chroot from disk if it has been dumped."""
    safe_rmtree(self.path())

  def debug(self, msg):
    self._logger.debug(msg)

  def path(self):
    return os.path.realpath(self._builder.path())

  def pex(self):
    return PEX(self.path(), interpreter=self._interpreter)

  def package_pex(self, filename):
    """Package into a PEX zipfile.

    :param filename: The filename where the PEX should be stored.
    """
    self._builder.build(filename)

  def _dump_library(self, library):
    def copy_to_chroot(base, path, add_function):
      src = os.path.join(get_buildroot(), base, path)
      add_function(src, path)

    self.debug('  Dumping library: {}'.format(library))
    for relpath in library.sources_relative_to_source_root():
      try:
        copy_to_chroot(library.target_base, relpath, self._builder.add_source)
      except OSError:
        logger.error("Failed to copy {path} for library {library}"
                     .format(path=os.path.join(library.target_base, relpath),
                             library=library))
        raise

    for resources_tgt in library.resources:
      for resource_file_from_source_root in resources_tgt.sources_relative_to_source_root():
        try:
          copy_to_chroot(resources_tgt.target_base, resource_file_from_source_root,
                         self._builder.add_resource)
        except OSError:
          logger.error("Failed to copy {path} for resource {resource}"
                       .format(path=os.path.join(resources_tgt.target_base,
                                                 resource_file_from_source_root),
                               resource=resources_tgt.address.spec))
          raise

  def _dump_requirement(self, req):
    self.debug('  Dumping requirement: {}'.format(req))
    self._builder.add_requirement(req)

  def _dump_distribution(self, dist):
    self.debug('  Dumping distribution: .../{}'.format(os.path.basename(dist.location)))
    self._builder.add_distribution(dist)

  def _generate_requirement(self, library, builder_cls):
    library_key = self._key_generator.key_for_target(library)
    builder = builder_cls(target=library,
                          root_dir=get_buildroot(),
                          target_suffix='-' + library_key.hash[:8])

    cache_dir = os.path.join(self._artifact_cache_root, library_key.id)
    if self._build_invalidator.needs_update(library_key):
      sdist = builder.build(interpreter=self._interpreter)
      safe_mkdir(cache_dir)
      shutil.copy(sdist, os.path.join(cache_dir, os.path.basename(sdist)))
      self._build_invalidator.update(library_key)

    return PythonRequirement(builder.requirement_string(), repository=cache_dir, use_2to3=True)

  def _generate_thrift_requirement(self, library):
    thrift_builder = functools.partial(PythonThriftBuilder,
                                       thrift_binary_factory=self._thrift_binary_factory,
                                       workdir=safe_mkdtemp(dir=self.path(), prefix='thrift.'))
    return self._generate_requirement(library, thrift_builder)

  def _generate_antlr_requirement(self, library):
    antlr_builder = functools.partial(PythonAntlrBuilder,
                                      ivy_bootstrapper=self._ivy_bootstrapper,
                                      workdir=safe_mkdtemp(dir=self.path(), prefix='antlr.'))
    return self._generate_requirement(library, antlr_builder)

  def resolve(self, targets):
    children = defaultdict(OrderedSet)

    def add_dep(trg):
      # Currently we handle all of our code generation, so we don't want to operate over any
      # synthetic targets injected upstream.
      # TODO(John Sirois): Revisit this when building a proper python product pipeline.
      if trg.is_synthetic:
        return

      for target_type, target_key in self._VALID_DEPENDENCIES.items():
        if isinstance(trg, target_type):
          children[target_key].add(trg)
          return
        elif isinstance(trg, Dependencies):
          return
      raise self.InvalidDependencyException(trg)
    for target in targets:
      target.walk(add_dep)
    return children

  def dump(self):
    self.debug('Building chroot for {}:'.format(self._targets))
    targets = self.resolve(self._targets)

    for lib in targets['libraries'] | targets['binaries']:
      self._dump_library(lib)

    generated_reqs = OrderedSet()
    if targets['thrifts']:
      for thr in targets['thrifts']:
        generated_reqs.add(self._generate_thrift_requirement(thr))
      generated_reqs.add(PythonRequirement('thrift', use_2to3=True))

    for antlr in targets['antlrs']:
      generated_reqs.add(self._generate_antlr_requirement(antlr))

    reqs_from_libraries = OrderedSet()
    for req_lib in targets['reqs']:
      for req in req_lib.payload.requirements:
        reqs_from_libraries.add(req)

    reqs_to_build = OrderedSet()
    find_links = OrderedSet()

    for req in reqs_from_libraries | generated_reqs | self._extra_requirements:
      if not req.should_build(self._interpreter.python, Platform.current()):
        self.debug('Skipping {} based upon version filter'.format(req))
        continue
      reqs_to_build.add(req)
      self._dump_requirement(req.requirement)
      if req.repository:
        find_links.add(req.repository)

    distributions = self._resolve_multi(reqs_to_build, find_links)

    locations = set()
    for platform, dist_set in distributions.items():
      for dist in dist_set:
        if dist.location not in locations:
          self._dump_distribution(dist)
        locations.add(dist.location)

    if len(targets['binaries']) > 1:
      print('WARNING: Target has multiple python_binary targets!', file=sys.stderr)

    return self._builder

  def _resolve_multi(self, requirements, find_links):
    """Multi-platform dependency resolution for PEX files.

       Given a pants configuration and a set of requirements, return a list of distributions
       that must be included in order to satisfy them.  That may involve distributions for
       multiple platforms.

       :param requirements: A list of :class:`PythonRequirement` objects to resolve.
       :param find_links: Additional paths to search for source packages during resolution.
    """
    distributions = dict()
    platforms = self.get_platforms(self._platforms or self._python_setup.platforms)
    fetchers = self._python_repos.get_fetchers()
    fetchers.extend(Fetcher([path]) for path in find_links)
    context = self._python_repos.get_network_context()

    for platform in platforms:
      requirements_cache_dir = os.path.join(self._python_setup.resolver_cache_dir, str(self._interpreter.identity))
      distributions[platform] = resolve(
        requirements=[req.requirement for req in requirements],
        interpreter=self._interpreter,
        fetchers=fetchers,
        platform=platform,
        context=context,
        cache=requirements_cache_dir,
        cache_ttl=self._python_setup.resolver_cache_ttl)

    return distributions
