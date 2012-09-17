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

__author__ = 'Brian Wickman'

import os
import sys
import tempfile


from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_rmtree
from twitter.common.python.interpreter import PythonIdentity
from twitter.common.python.platforms import Platform

from twitter.pants.targets import PythonBinary

from twitter.pants.base import Config
from twitter.pants.base.artifact_cache import FileBasedArtifactCache
from twitter.pants.base.build_invalidator import CacheKeyGenerator
from twitter.pants.python.antlr_builder import PythonAntlrBuilder
from twitter.pants.python.thrift_builder import PythonThriftBuilder

from twitter.common.python.fetcher import Fetcher
from twitter.common.python.pex_builder import PEXBuilder

from twitter.pants.python.resolver import PythonResolver, SilentResolver


class ReqResolver(object):
  @staticmethod
  def fetcher(config):
    return Fetcher(
      repositories = config.getlist('python-setup', 'repos', []),
      indices = config.getlist('python-setup', 'indices', []),
      external = config.getbool('python-setup', 'allow_pypi', True),
      download_cache = config.get('python-setup', 'cache', default=None))

  @staticmethod
  def resolver(config, platform, python):
    return SilentResolver(
      caches = config.getlist('python-setup', 'local_eggs') +
                [config.get('python-setup', 'install_cache')],
      install_cache = config.get('python-setup', 'install_cache'),
      fetcher = ReqResolver.fetcher(config),
      platform = platform,
      python = python)

  @staticmethod
  def resolve(requirements, config, platforms, pythons, ignore_errors=False):
    reqset = OrderedSet()
    requirements = list(requirements)
    for platform in platforms:
      for python in pythons:
        resolver = ReqResolver.resolver(config, platform, python)
        for dist in resolver.resolve(requirements, ignore_errors=ignore_errors):
          reqset.add(dist)
    return list(reqset)


class PythonChroot(object):
  class BuildFailureException(Exception):
    def __init__(self, msg):
      Exception.__init__(self, msg)

  def __init__(self, target, root_dir, extra_targets=None, builder=None):
    self._config = Config.load()

    self._target = target
    self._root = root_dir
    self._key_generator = CacheKeyGenerator()
    self._extra_targets = list(extra_targets) if extra_targets is not None else []
    self._resolver = PythonResolver([self._target] + self._extra_targets)
    self._builder = builder or PEXBuilder(tempfile.mkdtemp())
    self._platforms = (Platform.current(),)
    self._pythons = (sys.version[:3],)

    artifact_cache_root = \
      os.path.join(self._config.get('python-setup', 'artifact_cache'), '%s' % PythonIdentity.get())
    self._artifact_cache = FileBasedArtifactCache(None, self._root, artifact_cache_root,
      self._builder.add_dependency_file)

    # TODO(wickman) Should this be in the binary builder?
    if isinstance(self._target, PythonBinary):
      self._platforms = self._target._platforms
      self._pythons = self._target._interpreters

  def __del__(self):
    if os.getenv('PANTS_LEAVE_CHROOT') is None:
      safe_rmtree(self.path())

  def debug(self, msg, indent=0):
    if os.getenv('PANTS_VERBOSE') is not None:
      print('%s%s' % (' ' * indent, msg))

  def path(self):
    return self._builder.path()

  def _dump_library(self, library):
    def translate_module(module):
      if module is None:
        module = ''
      return module.replace('.', os.path.sep)

    def copy_to_chroot(base, path, relative_to, add_function):
      src = os.path.join(self._root, base, path)
      dst = os.path.join(translate_module(relative_to), path)
      add_function(src, dst)

    self.debug('  Dumping library: %s [relative module: %s]' % (library, library.module))
    for filename in library.sources:
      copy_to_chroot(library.target_base, filename, library.module, self._builder.add_source)
    for filename in library.resources:
      copy_to_chroot(library.target_base, filename, library.module, self._builder.add_resource)

  def _dump_requirement(self, req, dynamic, repo):
    self.debug('  Dumping requirement: %s%s%s' % (str(req),
      ' (dynamic)' if dynamic else '', ' (repo: %s)' if repo else ''))
    self._builder.add_requirement(req, dynamic, repo)

  def _dump_distribution(self, dist):
    self.debug('  Dumping distribution: .../%s' % os.path.basename(dist.location))
    self._builder.add_distribution(dist)

  def _dump_bin(self, binary_name, base):
    src = os.path.join(self._root, base, binary_name)
    self.debug('  Dumping binary: %s' % binary_name)
    self._builder.set_executable(src, os.path.basename(src))

  def _dump_thrift_library(self, library):
    self._dump_built_library(library, PythonThriftBuilder(library, self._root))

  def _dump_antlr_library(self, library):
    self._dump_built_library(library, PythonAntlrBuilder(library, self._root))

  def _dump_built_library(self, library, builder):
    # TODO(wickman): Port this over to the Installer+Distiller and stop using FileBasedArtifactCache.
    absolute_sources = library.expand_files()
    absolute_sources.sort()
    cache_key = self._key_generator.key_for(library.id, absolute_sources)
    if self._artifact_cache.has(cache_key):
      self.debug('  Generating (cached) %s...' % library)
      self._artifact_cache.use_cached_files(cache_key)
    else:
      self.debug('  Generating %s...' % library)
      egg_file = builder.build_egg()
      if not egg_file:
        raise PythonChroot.BuildFailureException("Failed to build %s!" % library)
      src_egg_file = egg_file
      dst_egg_file = os.path.join(os.path.dirname(egg_file),
          cache_key.hash + '_' + os.path.basename(egg_file))
      self.debug('       %s => %s' % (src_egg_file, dst_egg_file))
      os.rename(src_egg_file, dst_egg_file)
      self._artifact_cache.insert(cache_key, [dst_egg_file])
      self._builder.add_egg(dst_egg_file)

  def dump(self):
    self.debug('Building PythonBinary %s:' % self._target)

    targets = self._resolver.resolve()

    for lib in targets['libraries']:
      self._dump_library(lib)

    for req in targets['reqs']:
      if not req.should_build():
        self.debug('Skipping %s based upon version filter' % req)
        continue
      self._dump_requirement(req._requirement, req._dynamic, req._repository)

    for dist in ReqResolver.resolve(
        (req._requirement for req in targets['reqs'] if req.should_build()),
        self._config, self._platforms, self._pythons,
        ignore_errors=self._builder.info().ignore_errors):
      self._dump_distribution(dist)

    for thr in targets['thrifts']:
      self._dump_thrift_library(thr)

    for antlr in targets['antlrs']:
      self._dump_antlr_library(antlr)

    if len(targets['binaries']) > 1:
      print('WARNING: Target has multiple python_binary targets!', file=sys.stderr)

    for binary in targets['binaries']:
      if len(binary.sources) > 0:
        self._dump_bin(binary.sources[0], binary.target_base)

    return self._builder
