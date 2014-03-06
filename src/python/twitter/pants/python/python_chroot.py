# ==================================================================================================
# Copyright 2011 Twitter, Inc.
# --------------------------------------------------------------------------------------------------
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this work except in compliance with the License.
# You may obtain a copy of the License in the LICENSE file, or at:
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==================================================================================================

from __future__ import print_function

from collections import defaultdict
import os
import random
import shutil
import sys
import tempfile

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_mkdir, safe_rmtree
from twitter.common.python.interpreter import PythonInterpreter
from twitter.common.python.pex_builder import PEXBuilder
from twitter.common.python.platforms import Platform
from twitter.pants.base.build_invalidator import BuildInvalidator, CacheKeyGenerator
from twitter.pants.base.config import Config
from twitter.pants.base.parse_context import ParseContext
from twitter.pants.targets.python_antlr_library import PythonAntlrLibrary
from twitter.pants.targets.python_binary import PythonBinary
from twitter.pants.targets.python_library import PythonLibrary
from twitter.pants.targets.python_requirement import PythonRequirement
from twitter.pants.targets.python_tests import PythonTests
from twitter.pants.targets.python_thrift_library import PythonThriftLibrary

from .antlr_builder import PythonAntlrBuilder
from .python_setup import PythonSetup
from .resolver import resolve_multi
from .thrift_builder import PythonThriftBuilder


class PythonChroot(object):
  _VALID_DEPENDENCIES = {
    PythonLibrary: 'libraries',
    PythonRequirement: 'reqs',
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
               target,
               root_dir,
               extra_targets=None,
               builder=None,
               platforms=None,
               interpreter=None,
               conn_timeout=None):
    self._config = Config.load()
    self._target = target
    self._root = root_dir
    self._platforms = platforms
    self._interpreter = interpreter or PythonInterpreter.get()
    self._extra_targets = list(extra_targets) if extra_targets is not None else []
    self._builder = builder or PEXBuilder(tempfile.mkdtemp(), interpreter=self._interpreter)

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
      src = os.path.join(self._root, base, path)
      add_function(src, path)

    self.debug('  Dumping library: %s' % library)
    for filename in library.sources:
      copy_to_chroot(library.target_base, filename, self._builder.add_source)
    for filename in library.resources:
      copy_to_chroot(library.target_base, filename, self._builder.add_resource)

  def _dump_requirement(self, req, dynamic, repo):
    self.debug('  Dumping requirement: %s%s%s' % (str(req),
      ' (dynamic)' if dynamic else '', ' (repo: %s)' % repo if repo else ''))
    self._builder.add_requirement(req, dynamic, repo)

  def _dump_distribution(self, dist):
    self.debug('  Dumping distribution: .../%s' % os.path.basename(dist.location))
    self._builder.add_distribution(dist)

  def _generate_requirement(self, library, builder_cls):
    library_key = self._key_generator.key_for_target(library)
    builder = builder_cls(library, self._root, self._config, '-' + library_key.hash[:8])

    cache_dir = os.path.join(self._egg_cache_root, library_key.id)
    if self._build_invalidator.needs_update(library_key):
      sdist = builder.build(interpreter=self._interpreter)
      safe_mkdir(cache_dir)
      shutil.copy(sdist, os.path.join(cache_dir, os.path.basename(sdist)))
      self._build_invalidator.update(library_key)

    with ParseContext.temp():
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
      raise self.InvalidDependencyException(trg)
    for target in targets:
      target.walk(add_dep)
    return children

  def dump(self):
    self.debug('Building PythonBinary %s:' % self._target)

    targets = self.resolve([self._target] + self._extra_targets)

    for lib in targets['libraries'] | targets['binaries']:
      self._dump_library(lib)

    generated_reqs = OrderedSet()
    if targets['thrifts']:
      for thr in set(targets['thrifts']):
        if thr not in self.MEMOIZED_THRIFTS:
          self.MEMOIZED_THRIFTS[thr] = self._generate_thrift_requirement(thr)
        generated_reqs.add(self.MEMOIZED_THRIFTS[thr])
      with ParseContext.temp():
        # trick pants into letting us add this python requirement, otherwise we get
        # TargetDefinitionException: Error in target BUILD.temp:thrift: duplicate to
        # PythonRequirement(thrift)
        #
        # TODO(wickman) Instead of just blindly adding a PythonRequirement for thrift, we
        # should first detect if any explicit thrift requirements have been added and use
        # those.  Only if they have not been supplied should we auto-inject it.
        generated_reqs.add(PythonRequirement('thrift', use_2to3=True,
            name='thrift-' + ''.join(random.sample('0123456789abcdef' * 8, 8))))

    for antlr in targets['antlrs']:
      generated_reqs.add(self._generate_antlr_requirement(antlr))

    targets['reqs'] |= generated_reqs
    reqs_to_build = OrderedSet()
    for req in targets['reqs']:
      if not req.should_build(self._interpreter.python, Platform.current()):
        self.debug('Skipping %s based upon version filter' % req)
        continue
      reqs_to_build.add(req)
      self._dump_requirement(req._requirement, False, req._repository)

    platforms = self._platforms
    if isinstance(self._target, PythonBinary):
      platforms = self._target.platforms
    distributions = resolve_multi(
         self._config,
         reqs_to_build,
         interpreter=self._interpreter,
         platforms=platforms)

    locations = set()
    for platform, dist_set in distributions.items():
      for dist in dist_set:
        if dist.location not in locations:
          self._dump_distribution(dist)
        locations.add(dist.location)

    if len(targets['binaries']) > 1:
      print('WARNING: Target has multiple python_binary targets!', file=sys.stderr)

    return self._builder
