# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import shutil
import sys
import tempfile
from collections import defaultdict

from pex.interpreter import PythonInterpreter
from pex.pex_builder import PEXBuilder
from pex.platforms import Platform
from twitter.common.collections import OrderedSet

from pants.backend.codegen.targets.python_antlr_library import PythonAntlrLibrary
from pants.backend.codegen.targets.python_thrift_library import PythonThriftLibrary
from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.core.targets.prep_command import PrepCommand
from pants.backend.python.antlr_builder import PythonAntlrBuilder
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.python_setup import PythonRepos, PythonSetup
from pants.backend.python.resolver import resolve_multi
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.thrift_builder import PythonThriftBuilder
from pants.base.build_environment import get_buildroot
from pants.base.build_invalidator import BuildInvalidator, CacheKeyGenerator
from pants.util.dirutil import safe_mkdir, safe_rmtree


logger = logging.getLogger(__name__)

class PythonChroot(object):
  _VALID_DEPENDENCIES = {
    PrepCommand: 'prep',
    PythonLibrary: 'libraries',
    PythonRequirementLibrary: 'reqs',
    PythonBinary: 'binaries',
    PythonThriftLibrary: 'thrifts',
    PythonAntlrLibrary: 'antlrs',
    PythonTests: 'tests'
  }

  MEMOIZED_THRIFTS = {}

  class InvalidDependencyException(Exception):
    def __init__(self, target):
      Exception.__init__(self, "Not a valid Python dependency! Found: {}".format(target))

  # TODO: A little extra push and we can get rid of the 'context' argument.
  def __init__(self,
               context,
               python_setup,
               python_repos,
               targets,
               extra_requirements=None,
               builder=None,
               platforms=None,
               interpreter=None):
    self.context = context
    self._python_setup = python_setup
    self._python_repos = python_repos

    self._targets = targets
    self._extra_requirements = list(extra_requirements) if extra_requirements else []
    self._platforms = platforms
    self._interpreter = interpreter or PythonInterpreter.get()
    self._builder = builder or PEXBuilder(os.path.realpath(tempfile.mkdtemp()),
                                          interpreter=self._interpreter)

    # Note: unrelated to the general pants artifact cache.
    self._egg_cache_root = os.path.join(
      self._python_setup.scratch_dir, 'artifacts', str(self._interpreter.identity))

    self._key_generator = CacheKeyGenerator()
    self._build_invalidator = BuildInvalidator( self._egg_cache_root)

  def delete(self):
    """Deletes this chroot from disk if it has been dumped."""
    safe_rmtree(self.path())

  def __del__(self):
    if os.getenv('PANTS_LEAVE_CHROOT') is None:
      self.delete()
    else:
      self.debug('Left chroot at {}'.format(self.path()))

  @property
  def builder(self):
    return self._builder

  def debug(self, msg, indent=0):
    if os.getenv('PANTS_VERBOSE') is not None:
      print('{}{}'.format(' ' * indent, msg))

  def path(self):
    return os.path.realpath(self._builder.path())

  def _dump_library(self, library):
    def copy_to_chroot(base, path, add_function):
      src = os.path.join(get_buildroot(), base, path)
      add_function(src, path)

    self.debug('  Dumping library: {}'.format(library))
    for relpath in library.sources_relative_to_source_root():
      try:
        copy_to_chroot(library.target_base, relpath, self._builder.add_source)
      except OSError as e:
        logger.error("Failed to copy {path} for library {library}"
                     .format(path=os.path.join(library.target_base, relpath),
                             library=library))
        raise

    for resources_tgt in library.resources:
      for resource_file_from_source_root in resources_tgt.sources_relative_to_source_root():
        try:
          copy_to_chroot(resources_tgt.target_base, resource_file_from_source_root,
                         self._builder.add_resource)
        except OSError as e:
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
    builder = builder_cls(library, get_buildroot(),
                          self.context.options, '-' + library_key.hash[:8])

    cache_dir = os.path.join(self._egg_cache_root, library_key.id)
    if self._build_invalidator.needs_update(library_key):
      sdist = builder.build(interpreter=self._interpreter)
      safe_mkdir(cache_dir)
      shutil.copy(sdist, os.path.join(cache_dir, os.path.basename(sdist)))
      self._build_invalidator.update(library_key)

    return PythonRequirement(builder.requirement_string(), repository=cache_dir, use_2to3=True)

  def _generate_thrift_requirement(self, library):
    return self._generate_requirement(library, PythonThriftBuilder)

  def _generate_antlr_requirement(self, library):
    return self._generate_requirement(library, PythonAntlrBuilder)

  def resolve(self, targets):
    children = defaultdict(OrderedSet)
    def add_dep(trg):
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
      for thr in set(targets['thrifts']):
        if thr not in self.MEMOIZED_THRIFTS:
          self.MEMOIZED_THRIFTS[thr] = self._generate_thrift_requirement(thr)
        generated_reqs.add(self.MEMOIZED_THRIFTS[thr])

      generated_reqs.add(PythonRequirement('thrift', use_2to3=True))

    for antlr in targets['antlrs']:
      generated_reqs.add(self._generate_antlr_requirement(antlr))

    reqs_from_libraries = OrderedSet()
    for req_lib in targets['reqs']:
      for req in req_lib.payload.requirements:
        reqs_from_libraries.add(req)

    reqs_to_build = OrderedSet()
    find_links = []

    for req in reqs_from_libraries | generated_reqs | self._extra_requirements:
      if not req.should_build(self._interpreter.python, Platform.current()):
        self.debug('Skipping {} based upon version filter'.format(req))
        continue
      reqs_to_build.add(req)
      self._dump_requirement(req.requirement)
      if req.repository:
        find_links.append(req.repository)

    distributions = resolve_multi(
         self._python_setup,
         self._python_repos,
         reqs_to_build,
         interpreter=self._interpreter,
         platforms=self._platforms,
         ttl=self.context.options.for_global_scope().python_chroot_requirements_ttl,
         find_links=find_links)

    locations = set()
    for platform, dist_set in distributions.items():
      for dist in dist_set:
        if dist.location not in locations:
          self._dump_distribution(dist)
        locations.add(dist.location)

    if len(targets['binaries']) > 1:
      print('WARNING: Target has multiple python_binary targets!', file=sys.stderr)

    return self._builder
