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

__author__ = 'Brian Wickman'

import copy
import errno
import os
import pkgutil
import random
import shutil
import sys
import tempfile

from twitter.common.python.dependency import PythonDependency
from twitter.common.python.environment import PythonEnvironment
from twitter.common.contextutil import temporary_dir
from twitter.pants.base import Target, Address

from twitter.pants.targets import (
  PythonBinary, PythonEgg, PythonLibrary, PythonAntlrLibrary,
  PythonThriftLibrary, PythonTests)

from twitter.pants.base.build_cache import BuildCache
from twitter.pants.python.antlr_builder import PythonAntlrBuilder
from twitter.pants.python.thrift_builder import PythonThriftBuilder
from twitter.pants.targets.with_sources import TargetWithSources

class PythonChroot(object):
  class InvalidDependencyException(Exception):
    def __init__(self, target):
      Exception.__init__(self, "Not a valid Python dependency! Found: %s" % target)

  class BuildFailureException(Exception):
    def __init__(self, target):
      Exception.__init__(self, "Not a valid Python dependency! Found: %s" % target)

  def __init__(self, target, root_dir, extra_targets=None):
    self._target = target
    self._root = root_dir
    self._cache = BuildCache(os.path.join(root_dir, '.pants.d', 'py_artifact_cache'))
    self._extra_targets = list(extra_targets) if extra_targets is not None else []
    self._extra_targets.append(self._get_common_python())
    distdir = os.path.join(root_dir, 'dist')
    distpath = tempfile.mktemp(dir=distdir, prefix=target.name)
    self.env = PythonEnvironment(distpath)

  def __del__(self):
    if os.getenv('PANTS_LEAVE_CHROOT') is None:
      try:
        shutil.rmtree(self.path())
      except OSError as e:
        if e.errno != errno.ENOENT:
          raise

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

    template = library._create_template_data()
    print '  Dumping library: %s [relative module: %s]' % (library, template.module)
    for filename in template.sources:
      copy_to_chroot(template.template_base, filename, template.module, self.env.add_source)
    for filename in template.resources:
      copy_to_chroot(template.template_base, filename, template.module, self.env.add_resource)

  def _dump_egg(self, egg):
    target_name = os.path.pathsep.join(sorted(os.path.basename(e) for e in egg.eggs))
    cache_key = self._cache.key_for(target_name, egg.eggs)
    if self._cache.needs_update(cache_key):
      print '  Dumping egg: %s' % egg
      prefixes, all_added_files = set(), set()
      for egg_path in egg.eggs:
        egg_dep = PythonDependency.from_eggs(egg_path)
        prefix, added_files = self.env.add_dependency(egg_dep)
        all_added_files.update(added_files)
        prefixes.add(prefix)
      assert len(prefixes) == 1, 'Ambiguous egg environment!'
      self._cache.update(cache_key, all_added_files, artifact_root=prefixes.pop())
    else:
      print '  Dumping (cached) egg: %s' % egg
      self._cache.use_cached_files(cache_key, self.env.add_dependency_file)

  def _dump_setuptools(self):
    SETUPTOOLS = 'distribute-0.6.21-py2.6.egg'
    print '  Dumping setuptools: %s' % SETUPTOOLS
    data = pkgutil.get_data(__name__, os.path.join('bootstrap', SETUPTOOLS))
    with temporary_dir() as tempdir:
      egg_path = os.path.join(tempdir, SETUPTOOLS)
      with open(egg_path, 'w') as fp:
        fp.write(data)
      egg_dep = PythonDependency.from_eggs(egg_path)
      self.env.add_dependency(egg_dep)

  # TODO(wickman) Just add write() to self.env and do this with pkg_resources or
  # just build an egg for twitter.common.python.
  def _get_common_python(self):
    return Target.get(Address.parse(self._root, 'src/python/twitter/common/python'))

  def _dump_bin(self, binary_name, base):
    src = os.path.join(self._root, base, binary_name)
    print '  Dumping binary: %s' % binary_name
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
      print '  Generating (cached) %s...' % library
      self._cache.use_cached_files(cache_key, self.env.add_dependency_file)
    else:
      print '  Generating %s...' % library
      egg_file = builder.build_egg()

      if egg_file:
        src_egg_file = egg_file
        dst_egg_file = os.path.join(os.path.dirname(egg_file),
            cache_key.hash + '_' + os.path.basename(egg_file))
        os.rename(src_egg_file, dst_egg_file)
        self._cache.update(cache_key, [dst_egg_file])
        egg_dep = PythonDependency.from_eggs(dst_egg_file)

        for pkg in builder.packages():
          print '    found namespace: %s' % pkg
        print '    copying...',
        self.env.add_dependency(egg_dep)
        print 'done.'
      else:
        print '   Failed!'
        raise PythonChroot.BuildFailureException("Failed to build %s!" % library)

  def build_dep_tree(self, target):
    libraries = set()
    eggs = set()
    binaries = set()
    thrifts = set()
    antlrs = set()

    def add_dep(trg):
      if isinstance(trg, PythonLibrary):
        if trg.sources or trg.resources:
          libraries.add(trg)
        for egg in [dep for dep in trg.dependencies if isinstance(dep, PythonEgg)]:
          eggs.add(egg)
      elif isinstance(trg, PythonEgg):
        eggs.add(trg)
      elif isinstance(trg, PythonBinary):
        binaries.add(trg)
      elif isinstance(trg, PythonThriftLibrary):
        thrifts.add(trg)
      elif isinstance(trg, PythonAntlrLibrary):
        antlrs.add(trg)
      elif isinstance(trg, PythonTests):
        # do not dump test sources/resources, but dump their
        # dependencies.
        pass
      else:
        raise PythonChroot.InvalidDependencyException(trg)

    target.walk(lambda t: add_dep(t), lambda typ: not isinstance(typ, PythonEgg))
    return libraries, eggs, binaries, thrifts, antlrs

  def aggregate_targets(self, targets):
    libraries, eggs, binaries, thrifts, antlrs = set(), set(), set(), set(), set()

    for target in targets:
      (addl_libraries,
       addl_eggs,
       addl_binaries,
       addl_thrifts,
       addl_antlrs) = self.build_dep_tree(target)
      libraries.update(addl_libraries)
      eggs.update(addl_eggs)
      binaries.update(addl_binaries)
      thrifts.update(addl_thrifts)
      antlrs.update(addl_antlrs)

    return libraries, eggs, binaries, thrifts, antlrs

  def dump(self):
    print 'Building PythonBinary %s:' % self._target
    libraries, eggs, binaries, thrifts, antlrs = self.aggregate_targets(
      [self._target] + self._extra_targets)

    for lib in libraries:
      self._dump_library(lib)
    self._dump_setuptools()
    for egg in eggs:
      self._dump_egg(egg)
    for thr in thrifts:
      self._dump_thrift_library(thr)
    for antlr in antlrs:
      self._dump_antlr_library(antlr)
    if len(binaries) > 1:
      print >> sys.stderr, 'WARNING: Target has multiple python_binary targets!'
    for binary in binaries:
      self._dump_bin(binary.sources[0], binary.target_base)
    self.env.freeze()
    return self.env
