# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import itertools
import os
import subprocess
import sys

from twitter.common.collections import OrderedSet

from pants.backend.codegen.targets.python_thrift_library import PythonThriftLibrary
from pants.backend.python.code_generator import CodeGenerator
from pants.base.build_environment import get_buildroot
from pants.util.dirutil import safe_walk
from pants.util.memo import memoized_property


class PythonThriftBuilder(CodeGenerator):
  """Generate Python code from thrift IDL files."""
  class UnknownPlatformException(CodeGenerator.Error):

    def __init__(self, platform):
      super(PythonThriftBuilder.UnknownPlatformException, self).__init__(
          'Unknown platform: {}!'.format(str(platform)))

  def __init__(self, thrift_binary_factory, workdir, target, root_dir, target_suffix=None):
    super(PythonThriftBuilder, self).__init__(workdir, target, root_dir,
                                              target_suffix=target_suffix)
    self._thrift_binary_factory = thrift_binary_factory

  @property
  def install_requires(self):
    return ['thrift']

  @memoized_property
  def _thrift_binary(self):
    return self._thrift_binary_factory().path

  def run_thrifts(self):
    """Generate Python thrift code."""
    bases = OrderedSet()

    def collect_bases(target):
      if isinstance(target, PythonThriftLibrary):
        bases.add(os.path.join(get_buildroot(), target.target_base))

    self.target.walk(collect_bases)

    for source in self.target.payload.sources.relative_to_buildroot():
      if not self._run_thrift(bases, os.path.join(get_buildroot(), source)):
        raise PythonThriftBuilder.CodeGenerationException(
          "Could not generate .py from {}!".format(source))

  def _run_thrift(self, bases, source):
    include_paths = list(itertools.chain.from_iterable(('-I', base) for base in bases))

    args = [
             self._thrift_binary,
             '--gen',
             'py:new_style',
             '-o', self.codegen_root] + include_paths + [source]

    po = subprocess.Popen(args, cwd=self.chroot.path())
    rv = po.wait()
    if rv != 0:
      comm = po.communicate()
      print('thrift generation failed!', file=sys.stderr)
      print('STDOUT', file=sys.stderr)
      print(comm[0], file=sys.stderr)
      print('STDERR', file=sys.stderr)
      print(comm[1], file=sys.stderr)
    return rv == 0

  @property
  def package_dir(self):
    return "gen-py"

  def generate(self):
    # auto-generate the python files that we bundle up
    self.run_thrifts()

    # Thrift generates code with all parent namespaces with empty __init__.py's. Generally
    # speaking we want to drop anything w/o an __init__.py, and for anything with an __init__.py,
    # we want to explicitly make it a namespace package, hence the hoops here.
    for root, _, files in safe_walk(os.path.normpath(self.package_root)):
      reldir = os.path.relpath(root, self.package_root)
      if reldir == '.':  # skip root
        continue
      if '__init__.py' not in files:  # skip non-packages
        continue
      init_py_abspath = os.path.join(root, '__init__.py')
      module_path = self.path_to_module(reldir)
      self.created_packages.add(module_path)
      if os.path.getsize(init_py_abspath) == 0:  # empty __init__, translate to namespace package
        with open(init_py_abspath, 'wb') as f:
          f.write(b"__import__('pkg_resources').declare_namespace(__name__)")
        self.created_namespace_packages.add(module_path)
      else:
        # non-empty __init__, this is a leaf package, usually with ttypes and constants, leave as-is
        pass

    if not self.created_packages:
      raise self.CodeGenerationException('No Thrift structures declared in {}!'.format(self.target))
