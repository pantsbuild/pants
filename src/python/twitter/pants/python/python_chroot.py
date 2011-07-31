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

import os
import shutil
import sys
import random
import pkgutil

from twitter.pants.base import Chroot

from twitter.pants.targets import PythonBinary
from twitter.pants.targets import PythonEgg
from twitter.pants.targets import PythonLibrary
from twitter.pants.targets import PythonAntlrLibrary
from twitter.pants.targets import PythonThriftLibrary
from twitter.pants.targets import PythonTests

from twitter.pants.python.antlr_builder import PythonAntlrBuilder
from twitter.pants.python.thrift_builder import PythonThriftBuilder

class PythonChroot(object):
  class InvalidDependencyException(Exception):
    def __init__(self, target):
      Exception.__init__(self, "Not a valid Python dependency! Found: %s" % target)

  class BuildFailureException(Exception):
    def __init__(self, target):
      Exception.__init__(self, "Not a valid Python dependency! Found: %s" % target)

  def __init__(self, target, root_dir):
    self.target = target
    self.root = root_dir
    distdir = os.path.join(root_dir, 'dist')
    self.chroot = Chroot(root_dir, distdir, target.name)

  def __del__(self):
    shutil.rmtree(self.chroot.path())

  def path(self):
    return self.chroot.path()

  def _dump_library(self, library):
    def translate_module(module):
      if module is None:
        module=''
      return module.replace('.', os.path.sep)

    def copy_to_chroot(base, path, relative_to=None, label=None):
      src = os.path.join(base, path)
      dst = os.path.join(translate_module(relative_to), path)
      self.chroot.copy(src, dst, label)

    template = library._create_template_data()
    print '  Dumping library: %s [relative module: %s]' % (library, template.module)
    for filename in template.sources:
      copy_to_chroot(template.template_base, filename, template.module, 'sources')
    for filename in template.resources:
      copy_to_chroot(template.template_base, filename, template.module, 'resources')

  def _dump_inits(self):
    # iterate through self.digest and find missing __init__.py's
    relative_digest = self.chroot.get('sources')
    init_digest = set()
    for path in relative_digest:
      split_path = path.split(os.path.sep)
      for k in range(1, len(split_path)):
        sub_path = os.path.sep.join(split_path[0:k] + ['__init__.py'])
        if sub_path not in relative_digest and sub_path not in init_digest:
          print '  Dumping __init__: %s' % sub_path
          self.chroot.touch(sub_path)
          init_digest.add(sub_path)

  def _dump_egg(self, egg):
    print '  Dumping egg: %s' % egg
    for egg_path in egg.eggs:
      src = egg_path
      dst = os.path.join('.deps', os.path.basename(src))
      if os.path.isfile(src):
        self.chroot.copy(src, dst, 'resources')
      else:
        for src_dir, subdirs, files in os.walk(src):
          for f in files:
            self.chroot.copy(
              os.path.join(src_dir, f),
              os.path.join(dst, os.path.relpath(os.path.join(src_dir, f), src)),
              'resources')

  def _dump_setuptools(self):
    SETUPTOOLS = 'setuptools-0.6c11-py2.6.egg'
    print '  Dumping setuptools: %s' % SETUPTOOLS
    data = pkgutil.get_data(__name__, os.path.join('bootstrap', SETUPTOOLS))
    dst = os.path.join('.deps', SETUPTOOLS)
    self.chroot.write(data, dst, 'resources')

  def _dump_bin(self, binary_name, base):
    src = os.path.join(base, binary_name)
    print '  Dumping binary: %s' % binary_name
    self.chroot.copy(src, '__main__.py', 'sources')

  def _dump_thrift_library(self, library):
    print '  Generating %s...' % library
    self._dump_built_library(PythonThriftBuilder(library, self.root))

  def _dump_antlr_library(self, library):
    print '  Generating %s...' % library
    self._dump_built_library(PythonAntlrBuilder(library, self.root))

  def _dump_built_library(self, builder):
    egg_file = builder.build_egg()
    if egg_file:
      egg_file = os.path.relpath(egg_file, self.root)
      for pkg in builder.packages():
        print '    found namespace: %s' % pkg
      # make a random string to disambiguate possibly similarly-named eggs?
      randstr = ''.join(map(chr, random.sample(range(ord('a'), ord('z')), 8))) + '_'
      print '    copying...',
      self.chroot.copy(egg_file, os.path.join('.deps', randstr + os.path.basename(egg_file)), 'resources')
      print 'done.'
    else:
      print '   Failed!'
      raise PythonChroot.BuildFailureException(
        "Failed to build %s!" % library)

  def build_dep_tree(self, target):
    libraries = set()
    eggs = set()
    binaries = set()
    thrifts = set()
    antlrs = set()

    def add_dep(trg):
      if isinstance(trg, PythonLibrary):
        if trg.sources:
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
      return [dep for dep in trg.dependencies if not isinstance(dep, PythonEgg)]

    target.walk(lambda t: add_dep(t), lambda typ: not isinstance(typ, PythonEgg))

    return libraries, eggs, binaries, thrifts, antlrs

  def dump(self):
    print 'Building PythonBinary %s:' % self.target
    libraries, eggs, binaries, thrifts, antlrs = self.build_dep_tree(self.target)

    for lib in libraries:
      self._dump_library(lib)
    self._dump_inits()

    if eggs:
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
    return self.chroot
