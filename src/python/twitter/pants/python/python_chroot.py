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

import copy
import errno
import os
import pkgutil
import shutil
import sys
import tempfile

import pkg_resources

from twitter.common.contextutil import temporary_dir
from twitter.common.dirutil import safe_mkdir
from twitter.common.lang import Compatibility
from twitter.common.python.dependency import PythonDependency
from twitter.common.python.environment import PythonEnvironment
from twitter.common.python.reqfetcher import ReqFetcher
from twitter.common.python.reqbuilder import ReqBuilder
from twitter.common.python.interpreter import PythonIdentity
from twitter.common.quantity import Time, Amount
from twitter.pants.base import Target, Address

from twitter.pants.targets import (
  PythonBinary, PythonEgg, PythonLibrary, PythonAntlrLibrary,
  PythonRequirement, PythonThriftLibrary, PythonTests)

from twitter.pants.base import Config
from twitter.pants.base.build_cache import BuildCache
from twitter.pants.python.antlr_builder import PythonAntlrBuilder
from twitter.pants.python.thrift_builder import PythonThriftBuilder


if Compatibility.PY3:
  from urllib.request import urlopen
  from urllib.error import URLError
else:
  from urllib2 import urlopen, URLError


class PythonChroot(object):
  class InvalidDependencyException(Exception):
    def __init__(self, target):
      Exception.__init__(self, "Not a valid Python dependency! Found: %s" % target)

  class BuildFailureException(Exception):
    def __init__(self, target):
      Exception.__init__(self, "Not a valid Python dependency! Found: %s" % target)

  @staticmethod
  def can_contact_index(url, timeout=Amount(5, Time.SECONDS)):
    try:
      response = urlopen(url, timeout=timeout.as_(Time.SECONDS))
      return response.code == 200
    except URLError:
      return False

  def __init__(self, target, root_dir, extra_targets=None):
    self._config = Config.load()
    self._target = target
    self._root = root_dir
    self._cache = BuildCache(os.path.join(self._config.get('python-setup', 'artifact_cache'),
      '%s' % PythonIdentity.get()))
    self._extra_targets = list(extra_targets) if extra_targets is not None else []
    self._extra_targets.append(self._get_common_python())

    cachedir = self._config.get('python-setup', 'cache')
    safe_mkdir(cachedir)
    self._eggcache = cachedir

    local_repo = 'file://%s' % os.path.realpath(cachedir)
    self._repos = [local_repo] + self._config.getlist('python-setup', 'repos')
    self._fetcher = ReqFetcher(repos=self._repos, cache=cachedir)
    self._index = None
    for index in self._config.getlist('python-setup', 'indices'):
      if PythonChroot.can_contact_index(index):
        self._index = index
        break
    self._additional_reqs = set()

    distdir = self._config.getdefault('pants_distdir')
    distpath = tempfile.mktemp(dir=distdir, prefix=target.name)
    self.env = PythonEnvironment(distpath)

  def __del__(self):
    if os.getenv('PANTS_LEAVE_CHROOT') is None:
      try:
        shutil.rmtree(self.path())
      except OSError as e:
        if e.errno != errno.ENOENT:
          raise

  def debug(self, msg, indent=0):
    if os.getenv('PANTS_VERBOSE') is not None:
      print('%s%s' % (' ' * indent, msg))

  def path(self):
    return self.env.path()

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
      copy_to_chroot(library.target_base, filename, library.module, self.env.add_source)
    for filename in library.resources:
      copy_to_chroot(library.target_base, filename, library.module, self.env.add_resource)

  def _dump_egg(self, egg):
    if isinstance(egg, PythonEgg):
      target_name = os.path.pathsep.join(sorted(os.path.basename(e) for e in egg.eggs))
      cache_key = self._cache.key_for(target_name, egg.eggs)
      if self._cache.needs_update(cache_key):
        self.debug('  Dumping egg: %s' % egg)
        prefixes, all_added_files = set(), set()
        for egg_path in egg.eggs:
          egg_dep = PythonDependency.from_eggs(egg_path)
          prefix, added_files = self.env.add_dependency(egg_dep)
          all_added_files.update(added_files)
          prefixes.add(prefix)
        assert len(prefixes) == 1, 'Ambiguous egg environment!'
        self._cache.update(cache_key, all_added_files, artifact_root=prefixes.pop())
      else:
        self.debug('  Dumping (cached) egg: %s' % egg)
        self._cache.use_cached_files(cache_key, self.env.add_dependency_file)
    elif isinstance(egg, PythonDependency):
      self.debug('  Dumping PythonDependency: %s' % egg)
      self.env.add_dependency(egg)
    else:
      raise PythonChroot.InvalidDependencyException("Unknown egg dependency %s" % egg)

  def _dump_distribution(self, dist):
    self.debug('  Dumping distribution: .../%s' % os.path.basename(dist.location))
    egg_dep = PythonDependency.from_distributions(dist)
    self.env.add_dependency(egg_dep)

  # TODO(wickman) Just add write() to self.env and do this with pkg_resources or
  # just build an egg for twitter.common.python.
  def _get_common_python(self):
    return Target.get(Address.parse(self._root, 'src/python/twitter/common/python'))

  def _dump_bin(self, binary_name, base):
    src = os.path.join(self._root, base, binary_name)
    self.debug('  Dumping binary: %s' % binary_name)
    self.env.set_executable(src, os.path.basename(src))

  def _dump_thrift_library(self, library):
    self._dump_built_library(library, PythonThriftBuilder(library, self._root))

  def _dump_antlr_library(self, library):
    self._dump_built_library(library, PythonAntlrBuilder(library, self._root))

  def _dump_built_library(self, library, builder):
    absolute_sources = library.expand_files()
    absolute_sources.sort()
    cache_key = self._cache.key_for(library._create_id(), absolute_sources)
    if not self._cache.needs_update(cache_key):
      self.debug('  Generating (cached) %s...' % library)
      self._cache.use_cached_files(cache_key, self.env.add_dependency_file)
    else:
      self.debug('  Generating %s...' % library)
      egg_file = builder.build_egg()

      if egg_file:
        src_egg_file = egg_file
        dst_egg_file = os.path.join(os.path.dirname(egg_file),
            cache_key.hash + '_' + os.path.basename(egg_file))
        os.rename(src_egg_file, dst_egg_file)
        self._cache.update(cache_key, [dst_egg_file])
        egg_dep = PythonDependency.from_eggs(dst_egg_file)

        for pkg in builder.packages():
          self.debug('    found namespace: %s' % pkg)
        self.debug('    copying...')
        self.env.add_dependency(egg_dep)
        self.debug('done.')
      else:
        self.debug('   Failed!')
        raise PythonChroot.BuildFailureException("Failed to build %s!" % library)

  def aggregate_targets(self, targets):
    libraries, eggs, reqs, binaries, thrifts, antlrs = set(), set(), set(), set(), set(), set()
    for target in targets:
      (addl_libraries,
       addl_eggs,
       addl_reqs,
       addl_binaries,
       addl_thrifts,
       addl_antlrs) = self.build_dep_tree(target)

      libraries.update(addl_libraries)
      eggs.update(addl_eggs)
      reqs.update(addl_reqs)
      binaries.update(addl_binaries)
      thrifts.update(addl_thrifts)
      antlrs.update(addl_antlrs)

    return libraries, eggs, reqs, binaries, thrifts, antlrs

  def build_dep_tree(self, input_target):
    target = copy.deepcopy(input_target)
    common_python = self._get_common_python()
    if common_python not in target.dependencies:
      target.dependencies.add(common_python)

    libraries, eggs, reqs, binaries, thrifts, antlrs = set(), set(), set(), set(), set(), set()

    def add_dep(trg):
      if isinstance(trg, PythonLibrary):
        if trg.sources or trg.resources:
          libraries.add(trg)
        for dep in trg.dependencies:
          if isinstance(dep, PythonEgg):
            eggs.add(dep)
      elif isinstance(trg, PythonEgg):
        eggs.add(trg)
      elif isinstance(trg, PythonRequirement):
        reqs.add(trg)
      elif isinstance(trg, PythonBinary):
        binaries.add(trg)
      elif isinstance(trg, PythonThriftLibrary):
        thrifts.add(trg)
      elif isinstance(trg, PythonAntlrLibrary):
        antlrs.add(trg)
      elif isinstance(trg, PythonTests):
        pass
      else:
        raise PythonChroot.InvalidDependencyException(trg)
      return trg.dependencies if hasattr(trg, 'dependencies') else []
    target.walk(lambda t: add_dep(t))

    return libraries, eggs, reqs, binaries, thrifts, antlrs

  def cache_egg_if_necessary(self, egg):
    target_file = os.path.join(self._eggcache, os.path.basename(egg))
    if not os.path.exists(target_file):
      if os.path.isdir(egg):
        shutil.copytree(egg, target_file)
      else:
        shutil.copyfile(egg, target_file)

  def _dump_req(self, req):
    self.debug('    - Fetching requirement: %s' % req)
    fetched_egg = self._fetcher.fetch(req)
    if fetched_egg is None:
      print('ERROR: Could not find %s!' % req, file=sys.stderr)
    else:
      if fetched_egg.endswith('.egg'):
        self._dump_egg(PythonDependency.from_eggs(fetched_egg))
        self.cache_egg_if_necessary(fetched_egg)
      else:
        if self._index is None:
          self.debug('ERROR: Could not contact any indices!  Your application may not '
                     'work properly.')
          return
        self.debug('      => Building %s' % fetched_egg)
        distributions = ReqBuilder.install_requirement(fetched_egg,
          index=self._index,
          repositories=self._repos)
        if not distributions:
          print('WARNING: Unable to build a working distribution from %s!' % fetched_egg, file=sys.stderr)
          print('Your application may not work properly.', file=sys.stderr)
        else:
          for distribution in distributions:
            if distribution.location.endswith('.egg'):
              self.cache_egg_if_necessary(distribution.location)
            self._dump_distribution(distribution)

  def _dump_python_req(self, python_req):
    self.debug('  Dumping Requirement(%s)' % python_req.name)
    self._dump_req(python_req._requirement)

  def add_req(self, req):
    assert isinstance(req, pkg_resources.Requirement)
    self._additional_reqs.add(req)

  def dump(self):
    self.debug('Building PythonBinary %s:' % self._target)

    libraries, eggs, reqs, binaries, thrifts, antlrs = self.aggregate_targets(
      [self._target] + self._extra_targets)

    bare_reqs = set([pkg_resources.Requirement.parse('distribute')])
    bare_reqs.update(self._additional_reqs)

    for lib in libraries: self._dump_library(lib)
    for req in bare_reqs: self._dump_req(req)
    for egg in eggs: self._dump_egg(egg)
    for req in reqs: self._dump_python_req(req)
    for thr in thrifts: self._dump_thrift_library(thr)
    for antlr in antlrs: self._dump_antlr_library(antlr)
    if len(binaries) > 1:
      print('WARNING: Target has multiple python_binary targets!', file=sys.stderr)
    for binary in binaries: self._dump_bin(binary.sources[0], binary.target_base)
    self.env.freeze()
    return self.env
