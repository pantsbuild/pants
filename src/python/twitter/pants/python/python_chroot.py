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
import shutil

__author__ = 'Brian Wickman'

from collections import defaultdict
import os
import sys
import tempfile

from twitter.common.collections import OrderedSet
from twitter.common.dirutil import safe_rmtree, safe_mkdir_for
from twitter.common.python.interpreter import PythonIdentity
from twitter.common.python.pex_builder import PEXBuilder
from twitter.common.python.platforms import Platform

from twitter.pants.base import Config
from twitter.pants.base.build_invalidator import CacheKeyGenerator
from twitter.pants.targets import (
    PythonAntlrLibrary,
    PythonBinary,
    PythonLibrary,
    PythonRequirement,
    PythonTests,
    PythonThriftLibrary)

from .antlr_builder import PythonAntlrBuilder
from .thrift_builder import PythonThriftBuilder


def get_platforms(platform_list):
  def translate(platform):
    return Platform.current() if platform == 'current' else platform
  return tuple(map(translate, platform_list))


class MultiResolver(object):
  """
    A multi-platform Requirement resolver for Pants.
  """
  @classmethod
  def from_target(cls, config, target, conn_timeout=None):
    from twitter.common.python.fetcher import PyPIFetcher, Fetcher
    from twitter.common.python.resolver import Resolver
    from twitter.common.python.http import Crawler
    from twitter.common.quantity import Amount, Time

    conn_timeout_amount = Amount(conn_timeout, Time.SECONDS) if conn_timeout is not None else None

    crawler = Crawler(cache=config.get('python-setup', 'download_cache'),
                      conn_timeout=conn_timeout_amount)

    fetchers = []
    fetchers.extend(Fetcher([url]) for url in config.getlist('python-repos', 'repos', []))
    fetchers.extend(PyPIFetcher(url) for url in config.getlist('python-repos', 'indices', []))

    platforms = config.getlist('python-setup', 'platforms', ['current'])
    if isinstance(target, PythonBinary) and target.platforms:
      platforms = target.platforms

    return cls(
        platforms=get_platforms(platforms),
        resolver=Resolver(cache=config.get('python-setup', 'install_cache'),
                          crawler=crawler,
                          fetchers=fetchers,
                          install_cache=config.get('python-setup', 'install_cache'),
                          conn_timeout=conn_timeout_amount))

  def __init__(self, platforms, resolver):
    self._resolver = resolver
    self._platforms = platforms

  def resolve(self, requirements):
    requirements = list(requirements)
    for platform in self._platforms:
      self._resolver.resolve(requirements, platform=platform)
    return self._resolver.distributions()


class PythonChroot(object):
  _VALID_DEPENDENCIES = {
    PythonLibrary: 'libraries',
    PythonRequirement: 'reqs',
    PythonBinary: 'binaries',
    PythonThriftLibrary: 'thrifts',
    PythonAntlrLibrary: 'antlrs',
    PythonTests: 'tests'
  }

  class InvalidDependencyException(Exception):
    def __init__(self, target):
      Exception.__init__(self, "Not a valid Python dependency! Found: %s" % target)

  class BuildFailureException(Exception):
    def __init__(self, msg):
      Exception.__init__(self, msg)

  def __init__(self, target, root_dir, extra_targets=None, builder=None, conn_timeout=None):
    self._config = Config.load()
    self._target = target
    self._root = root_dir
    self._key_generator = CacheKeyGenerator()
    self._extra_targets = list(extra_targets) if extra_targets is not None else []
    self._resolver = MultiResolver.from_target(self._config, target, conn_timeout=conn_timeout)
    self._builder = builder or PEXBuilder(tempfile.mkdtemp())

    # Note: unrelated to the general pants artifact cache.
    self._egg_cache_root = os.path.join(self._config.get('python-setup', 'artifact_cache'),
                                        '%s' % PythonIdentity.get())

  def __del__(self):
    if os.getenv('PANTS_LEAVE_CHROOT') is None:
      safe_rmtree(self.path())
    else:
      print('Left chroot at %s' % self.path())

  @property
  def builder(self):
    return self._builder

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
      self.debug('    Copying %s -> %s' % (src, dst))
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
    self._dump_built_library(library, PythonThriftBuilder(library, self._root, self._config))

  def _dump_antlr_library(self, library):
    self._dump_built_library(library, PythonAntlrBuilder(library, self._root))

  def _dump_built_library(self, library, builder):
    # TODO(wickman): Port this over to the Installer+Distiller and stop using ArtifactCache.
    absolute_sources = library.expand_files()
    absolute_sources.sort()
    cache_key = self._key_generator.key_for(library.id, absolute_sources)
    cache_dir = os.path.join(self._egg_cache_root, cache_key.hash)
    if os.path.exists(cache_dir):
      self.debug('  Generating (cached) %s...' % library)
      # We have no idea what the egg path is, so we simply walk the directory.
      for dir_name, _, filenames in os.walk(cache_dir):
        for filename in filenames:
          self._builder.add_egg(os.path.join(dir_name, filename))
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
      cache_dir = os.path.join(self._egg_cache_root, cache_key.hash)
      cached_egg_file = os.path.join(cache_dir, os.path.relpath(dst_egg_file, self._root))
      try:
        safe_mkdir_for(cached_egg_file)
        shutil.copy(dst_egg_file, cached_egg_file)
      except:
        safe_rmtree(cache_dir)
        raise
      self._builder.add_egg(dst_egg_file)

  def resolve(self, targets):
    children = defaultdict(OrderedSet)
    def add_dep(trg):
      if trg.is_concrete:
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

    for lib in targets['libraries']:
      self._dump_library(lib)

    for req in targets['reqs']:
      if not req.should_build():
        self.debug('Skipping %s based upon version filter' % req)
        continue
      self._dump_requirement(req._requirement, req._dynamic, req._repository)

    for dist in self._resolver.resolve(
        req._requirement for req in targets['reqs'] if req.should_build()):
      self._dump_distribution(dist)

    if targets['thrifts']:
      default_thrift_version = self._config.get('python-thrift', 'default-version', default='0.9')
      thrift_versions = set()
      for thr in targets['thrifts']:
        self._dump_thrift_library(thr)
        thrift_version = thr.thrift_version or default_thrift_version
        thrift_versions.add(thrift_version)
      if len(thrift_versions) > 1:
        print('WARNING: Target has multiple thrift versions!')
      for version in thrift_versions:
        self._builder.add_requirement('thrift==%s' % version)
        for dist in self._resolver.resolve('thrift==%s' % version for version in thrift_versions):
          self._dump_distribution(dist)

    for antlr in targets['antlrs']:
      self._dump_antlr_library(antlr)

    if len(targets['binaries']) > 1:
      print('WARNING: Target has multiple python_binary targets!', file=sys.stderr)

    for binary in targets['binaries']:
      if len(binary.sources) > 0:
        self._dump_bin(binary.sources[0], binary.target_base)

    return self._builder
