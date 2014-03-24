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
import sys

from twitter.common.dirutil import safe_mkdir

from twitter.pants.ivy.bootstrapper import Bootstrapper
from twitter.pants.ivy.ivy import Ivy

from .code_generator import CodeGenerator


class PythonAntlrBuilder(CodeGenerator):
  """
    Antlr builder.
  """
  def run_antlrs(self, output_dir):
    args = [
      '-dependency', 'org.antlr', 'antlr', self.target.antlr_version,
      '-types', 'jar',
      '-main', 'org.antlr.Tool',
      '--', '-fo', output_dir
    ]
    for source in self.target.sources:
      abs_path = os.path.abspath(os.path.join(self.root, self.target.target_base, source))
      args.append(abs_path)

    try:
      ivy = Bootstrapper.default_ivy()
      ivy.execute(args=args)  # TODO: Needs a workunit, when we have a context here.
      return True
    except (Bootstrapper.Error, Ivy.Error) as e:
      print('ANTLR generation failed! %s' % e, file=sys.stderr)
      return False

  def generate(self):
    # Create the package structure.
    path = self.sdist_root

    package = ''
    for module_name in self.target.module.split('.'):
      path = os.path.join(path, module_name)
      if package == '':
        package = module_name
      else:
        package = package + '.' + module_name
      safe_mkdir(path)
      with open(os.path.join(path, '__init__.py'), 'w') as f:
        if package != self.target.module:  # Only write this in the non-leaf modules.
          f.write("__import__('pkg_resources').declare_namespace(__name__)")
          self.created_namespace_packages.add(package)
      self.created_packages.add(package)

    # autogenerate the python files that we bundle up
    self.run_antlrs(path)
