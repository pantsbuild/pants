# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import sys

from pants.backend.python.code_generator import CodeGenerator
from pants.base.build_environment import get_buildroot
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy import Ivy
from pants.util.dirutil import safe_mkdir


class PythonAntlrBuilder(CodeGenerator):
  """
    Antlr builder.
  """
  def run_antlrs(self, output_dir):
    # TODO(John Sirois): graduate to a JvmToolTask and/or merge with the java code gen AntlrGen
    # task.
    args = [
      '-dependency', 'org.antlr', 'antlr', self.target.antlr_version,
      '-types', 'jar',
      '-main', 'org.antlr.Tool',
      '--', '-fo', output_dir
    ]
    for source in self.target.sources_relative_to_buildroot():
      abs_path = os.path.join(get_buildroot(), source)
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
