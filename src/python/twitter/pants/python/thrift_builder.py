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
import subprocess

from twitter.common.dirutil import safe_rmtree
from twitter.common.dirutil.chroot import RelativeChroot

from twitter.pants.python.egg_builder import EggBuilder
from twitter.pants.targets.python_thrift_library import PythonThriftLibrary
from twitter.pants.thrift_util import calculate_compile_roots, select_thrift_binary

class PythonThriftBuilder(object):
  """
    Thrift builder.
  """
  class UnknownPlatformException(Exception):
    def __init__(self, platform):
      Exception.__init__(self, "Unknown platform: %s!" % str(platform))
  class CodeGenerationException(Exception): pass

  def __init__(self, target, root_dir, config):
    self.target = target
    self.root = root_dir
    self.config = config
    distdir = os.path.join(self.root, 'dist')
    self.chroot = RelativeChroot(root_dir, distdir, target.name)
    codegen_root = tempfile.mkdtemp(dir=self.chroot.path(), prefix='codegen.')
    self.codegen_root = os.path.relpath(codegen_root, self.chroot.path())
    self.detected_packages = set()
    self.detected_namespace_packages = set()

  def __del__(self):
    self.cleanup()

  def packages(self):
    return self.detected_packages

  def cleanup(self):
    safe_rmtree(self.chroot.path())

  def run_thrifts(self):
    def is_py_thrift(target):
      return isinstance(target, PythonThriftLibrary)
    bases, roots = calculate_compile_roots([self.target], is_py_thrift)

    for src in roots:
      if not self._run_thrift(src, bases):
        raise PythonThriftBuilder.CodeGenerationException(
          "Could not generate .py from %s!" % src)

  def _run_thrift(self, source, bases):
    thrift_file = source
    thrift_abs_path = os.path.join(self.root, thrift_file)
    thrift_abs_path = os.path.abspath(thrift_abs_path)

    args = [
      select_thrift_binary(self.config),
      '--gen',
      'py:new_style',
      '-recurse',
      '-o',
      self.codegen_root
    ]
    for base in bases:
      args.extend(('-I', base))
    args.append(thrift_abs_path)

    cwd = os.getcwd()
    os.chdir(self.chroot.path())
    try:
      po = subprocess.Popen(args)
    finally:
      os.chdir(cwd)
    rv = po.wait()
    if rv != 0:
      comm = po.communicate()
      print('thrift generation failed!', file=sys.stderr)
      print('STDOUT', file=sys.stderr)
      print(comm[0], file=sys.stderr)
      print('STDERR', file=sys.stderr)
      print(comm[1], file=sys.stderr)
    return rv == 0

  @staticmethod
  def path_to_module(path):
    return path.replace(os.path.sep, '.')

  def build_egg(self):
    # autogenerate the python files that we bundle up
    self.run_thrifts()

    genpy_root = os.path.join(self.chroot.path(), self.codegen_root, 'gen-py')
    for dir, _, files in os.walk(os.path.normpath(genpy_root)):
      reldir = os.path.relpath(dir, genpy_root)
      if reldir == '.': continue
      if '__init__.py' not in files: continue
      init_py_abspath = os.path.join(dir, '__init__.py')
      module_path = self.path_to_module(reldir)
      self.detected_packages.add(module_path)
      # A namespace package is one that is just a container for other
      # modules and subpackages. Setting their __init__.py files as follows
      # allows them to be distributed across multiple eggs. Without this you
      # couldn't have this egg share any package prefix with any other module
      # in any other egg or in the source tree.
      #
      # Note that the thrift compiler should always generate empty __init__.py
      # files, but we test for this anyway, just in case that changes.
      if len(files) == 1 and os.path.getsize(init_py_abspath) == 0:
        with open(init_py_abspath, 'wb') as f:
          f.write(b"__import__('pkg_resources').declare_namespace(__name__)")
        self.detected_namespace_packages.add(module_path)

    if not self.detected_packages:
      raise PythonThriftBuilder.CodeGenerationException(
        'No Thrift structures declared in %s!' % self.target)

    def dump_setup_py(packages, namespace_packages):
      boilerplate = """
from setuptools import setup

setup(name        = "%(target_name)s",
      version     = "dev",
      description = "autogenerated thrift bindings for %(target_name)s",
      package_dir = { "": "gen-py" },
      packages    = %(packages)s,
      namespace_packages = %(namespace_packages)s)
"""
      boilerplate = boilerplate % {
        'target_name': self.target._create_id(),
        'genpy_root': genpy_root,
        'packages': repr(list(packages)),
        'namespace_packages': repr(list(namespace_packages))
      }

      self.chroot.write(boilerplate.encode('utf-8'), os.path.join(self.codegen_root, 'setup.py'))
    dump_setup_py(self.detected_packages, self.detected_namespace_packages)

    egg_root = os.path.join(self.chroot.path(), self.codegen_root)
    egg_path = EggBuilder().build_egg(egg_root, self.target)
    return egg_path
