# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import functools
import os
import re
import shutil
import subprocess
import sys

from pants.backend.python.code_generator import CodeGenerator
from pants.backend.codegen.targets.python_thrift_library import PythonThriftLibrary
from pants.base.build_environment import get_buildroot
from pants.thrift_util import select_thrift_binary
from pants.util.keywords import replace_python_keywords_in_file
from pants.util.dirutil import safe_mkdir, safe_walk
from pants.util.strutil import ensure_binary


class PythonThriftBuilder(CodeGenerator):
  """Code Generator a  Python code from thrift IDL files."""
  class UnknownPlatformException(CodeGenerator.Error):
    def __init__(self, platform):
      super(PythonThriftBuilder.UnknownPlatformException, self).__init__(
          'Unknown platform: %s!' % str(platform))

  def __init__(self, target, root_dir, config, target_suffix=None):
    super(PythonThriftBuilder, self).__init__(target, root_dir, config, target_suffix=target_suffix)
    self._workdir = os.path.join(config.getdefault('pants_workdir'), 'thrift', 'py-thrift')

  @property
  def install_requires(self):
    return ['thrift']

  def run_thrifts(self):
    """
    Generate Python thrift code using thrift compiler specified in pants config.

    Thrift fields conflicting with Python keywords are suffixed with a trailing
    underscore (e.g.: from_).
    """

    def is_py_thrift(target):
      return isinstance(target, PythonThriftLibrary)

    all_thrifts = set()

    def collect_sources(target):
      abs_target_base = os.path.join(get_buildroot(), target.target_base)
      for source in target.payload.sources.relative_to_buildroot():
        source_root_relative_source = os.path.relpath(source, abs_target_base)
        all_thrifts.add((target.target_base, source_root_relative_source))

    self.target.walk(collect_sources, predicate=is_py_thrift)

    copied_sources = set()
    for base, relative_source in all_thrifts:
      abs_source = os.path.join(base, relative_source)
      copied_source = os.path.join(self._workdir, relative_source)

      safe_mkdir(os.path.dirname(copied_source))
      shutil.copyfile(abs_source, copied_source)
      copied_sources.add(replace_python_keywords_in_file(copied_source))

    for src in copied_sources:
      if not self._run_thrift(src):
        raise PythonThriftBuilder.CodeGenerationException("Could not generate .py from %s!" % src)

  def _run_thrift(self, source):
    args = [
        select_thrift_binary(self.config),
        '--gen',
        'py:new_style',
        '-o', self.codegen_root,
        '-I', self._workdir,
        os.path.abspath(source)]

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
      raise self.CodeGenerationException('No Thrift structures declared in %s!' % self.target)
