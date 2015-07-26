# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

from pants.backend.python.code_generator import CodeGenerator
from pants.base.build_environment import get_buildroot
from pants.base.exceptions import TaskError
from pants.ivy.bootstrapper import Bootstrapper
from pants.ivy.ivy import Ivy
from pants.util.dirutil import safe_mkdir


class PythonAntlrBuilder(CodeGenerator):
  """
    Antlr builder.
  """

  def __init__(self, ivy_bootstrapper, *args, **kwargs):
    super(PythonAntlrBuilder, self).__init__(*args, **kwargs)
    self._ivy_bootstrapper = ivy_bootstrapper

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
      ivy = self._ivy_bootstrapper.ivy()
      ivy.execute(args=args)  # TODO: Needs a workunit, when we have a context here.
    except (Bootstrapper.Error, Ivy.Error) as e:
      raise TaskError('ANTLR generation failed! {0}'.format(e))

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
