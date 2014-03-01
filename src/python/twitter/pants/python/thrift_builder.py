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

import os
import subprocess
import sys

from twitter.common.dirutil import safe_rmtree
from twitter.pants.base.build_environment import get_buildroot
from twitter.pants.python.code_generator import CodeGenerator
from twitter.pants.targets.python_thrift_library import PythonThriftLibrary
from twitter.pants.thrift_util import calculate_compile_roots, select_thrift_binary


class PythonThriftBuilder(CodeGenerator):
  class UnknownPlatformException(CodeGenerator.Error):
    def __init__(self, platform):
      super(PythonThriftBuilder.UnknownPlatformException, self).__init__(
          "Unknown platform: %s!" % str(platform))

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
    thrift_abs_path = os.path.abspath(os.path.join(self.root, thrift_file))

    args = [
      select_thrift_binary(self.config),
      '--gen',
      'py:new_style',
      '-recurse',
      '-o',
      self.codegen_root
    ]

    # Add bases as include paths to try.  Note that include paths and compile targets
    # should be uniformly relative, or uniformly absolute (in this case the latter).
    for base in bases:
      args.extend(('-I', os.path.join(get_buildroot(), base)))
    args.append(thrift_abs_path)

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
    # autogenerate the python files that we bundle up
    self.run_thrifts()

    # Thrift generates code with all parent namespaces with empty __init__.py's. Generally
    # speaking we want to drop anything w/o an __init__.py, and for anything with an __init__.py,
    # we want to explicitly make it a namespace package, hence the hoops here.
    for root, _, files in os.walk(os.path.normpath(self.package_root)):
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
      raise self.CodeGenerationException(
        'No Thrift structures declared in %s!' % self.target)
