# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from collections import defaultdict
import os
import shutil
import sys
import tempfile

from pex.interpreter import PythonInterpreter
from pex.pex_builder import PEXBuilder
from pex.platforms import Platform
from twitter.common.collections import OrderedSet

from pants.backend.codegen.targets.python_antlr_library import PythonAntlrLibrary
from pants.backend.codegen.targets.python_thrift_library import PythonThriftLibrary
from pants.backend.core.targets.dependencies import Dependencies
from pants.backend.python.antlr_builder import PythonAntlrBuilder
from pants.backend.python.python_requirement import PythonRequirement
from pants.backend.python.python_setup import PythonSetup
from pants.backend.python.resolver import resolve_multi
from pants.backend.python.targets.python_binary import PythonBinary
from pants.backend.python.targets.python_library import PythonLibrary
from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.backend.python.targets.python_tests import PythonTests
from pants.backend.python.thrift_builder import PythonThriftBuilder
from pants.base.build_environment import get_buildroot
from pants.base.build_invalidator import BuildInvalidator, CacheKeyGenerator
from pants.base.config import Config
from pants.util.dirutil import safe_mkdir, safe_rmtree


class PythonChroot(object):
  _VALID_DEPENDENCIES = {
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
      Exception.__init__(self, "Not a valid Python dependency! Found: %s" % target)

  def __init__(self,
               targets,
               extra_requirements=None,
               builder=None,
               platforms=None,
               interpreter=None,
               conn_timeout=None):
    self._config = Config.load()
    self._targets = targets
    self._extra_requirements = list(extra_requirements) if extra_requirements else []
    self._platforms = platforms
    self._interpreter = interpreter or PythonInterpreter.get()
    self._builder = builder or PEXBuilder(tempfile.mkdtemp(), interpreter=self._interpreter)
    self._conn_timeout = conn_timeout

    # Note: unrelated to the general pants artifact cache.
    self._egg_cache_root = os.path.join(
        PythonSetup(self._config).scratch_dir('artifact_cache', default_name='artifacts'),
        str(self._interpreter.identity))

    self._key_generator = CacheKeyGenerator()
    self._build_invalidator = BuildInvalidator( self._egg_cache_root)


  def __del__(self):
    if os.getenv('PANTS_LEAVE_CHROOT') is None:
      safe_rmtree(self.path())
    else:
      self.debug('Left chroot at %s' % self.path())

  @property
  def builder(self):
    return self._builder

  def debug(self, msg, indent=0):
    if os.getenv('PANTS_VERBOSE') is not None:
      print('%s%s' % (' ' * indent, msg))

  def path(self):
    return self._builder.path()

  def _dump_library(self, library):
    def copy_to_chroot(base, path, add_function):
      src = os.path.join(get_buildroot(), base, path)
      add_function(src, path)

    self.debug('  Dumping library: %s' % library)
    for relpath in library.sources_relative_to_source_root():
      copy_to_chroot(library.target_base, relpath, self._builder.add_source)

    for resources_tgt in library.resources:
      for resource_file_from_source_root in resources_tgt.sources_relative_to_source_root():
        copy_to_chroot(resources_tgt.target_base, resource_file_from_source_root,
                       self._builder.add_resource)

  def _dump_requirement(self, req, dynamic, repo):
    self.debug('  Dumping requirement: %s%s%s' % (str(req),
      ' (dynamic)' if dynamic else '', ' (repo: %s)' % repo if repo else ''))
    self._builder.add_requirement(req, dynamic, repo)

  def _dump_distribution(self, dist):
    self.debug('  Dumping distribution: .../%s' % os.path.basename(dist.location))
    self._builder.add_distribution(dist)

  def _generate_requirement(self, library, builder_cls):
    library_key = self._key_generator.key_for_target(library)
    builder = builder_cls(library, get_buildroot(), self._config, '-' + library_key.hash[:8])

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
    self.debug('Building chroot for %s:' % self._targets)
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
    for req in reqs_from_libraries | generated_reqs | self._extra_requirements:
      if not req.should_build(self._interpreter.python, Platform.current()):
        self.debug('Skipping %s based upon version filter' % req)
        continue
      reqs_to_build.add(req)
      self._dump_requirement(req._requirement, False, req._repository)

    distributions = resolve_multi(
         self._config,
         reqs_to_build,
         interpreter=self._interpreter,
         platforms=self._platforms,
         conn_timeout=self._conn_timeout)

    locations = set()
    for platform, dist_set in distributions.items():
      for dist in dist_set:
        if dist.location not in locations:
          self._dump_distribution(dist)
        locations.add(dist.location)

    if len(targets['binaries']) > 1:
      print('WARNING: Target has multiple python_binary targets!', file=sys.stderr)

    return self._builder
