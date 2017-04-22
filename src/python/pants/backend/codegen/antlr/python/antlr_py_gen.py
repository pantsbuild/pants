# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os

from pants.backend.codegen.antlr.python.python_antlr_library import PythonAntlrLibrary
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.backend.python.targets.python_library import PythonLibrary
from pants.base.exceptions import TaskError
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import target_option
from pants.task.simple_codegen_task import SimpleCodegenTask
from pants.util.dirutil import safe_mkdir, touch
from pants.util.memo import memoized_method


logger = logging.getLogger(__name__)


_ANTLR3_REV = '3.1.3'


# TODO: Refactor this and AntlrJavaGen to share a common base class with most of the functionality.
# In particular, doing so will add antlr4 and timestamp stripping support for Python.
# However, this refactoring will only  make sense once we modify PythonAntlrLibrary
# as explained below.
class AntlrPyGen(SimpleCodegenTask, NailgunTask):
  """Generate Python source code from ANTLR grammar files."""
  gentarget_type = PythonAntlrLibrary

  @classmethod
  def register_options(cls, register):
    super(AntlrPyGen, cls).register_options(register)
    # The ANTLR compiler.
    cls.register_jvm_tool(register, 'antlr3',
                          classpath=[JarDependency(org='org.antlr', name='antlr', rev=_ANTLR3_REV)],
                          classpath_spec='//:antlr-{}'.format(_ANTLR3_REV))
    # The ANTLR runtime python deps.
    register('--antlr3-deps', advanced=True, type=list, member_type=target_option,
             help='A list of specs pointing to dependencies of ANTLR3 generated code.')

  def find_sources(self, target, target_dir):
    # Ignore .tokens files.
    sources = super(AntlrPyGen, self).find_sources(target, target_dir)
    return [source for source in sources if source.endswith('.py')]

  def is_gentarget(self, target):
    return isinstance(target, PythonAntlrLibrary)

  def synthetic_target_type(self, target):
    return PythonLibrary

  def synthetic_target_extra_dependencies(self, target, target_workdir):
    return self._deps()

  @memoized_method
  def _deps(self):
    deps = self.get_options().antlr3_deps
    return list(self.resolve_deps(deps))

  def execute_codegen(self, target, target_workdir):
    if target.antlr_version != _ANTLR3_REV:
      # TODO: Deprecate the antlr_version argument to PythonAntlrLibrary and replace
      # it with a compiler= argument, that takes logical names (antlr3, antlr4), like
      # JavaAntlrLibrary.  We can't support arbitrary revisions on targets because we
      # have to register them as jvm tools before we see any targets.
      raise TaskError('Only antlr rev {} supported for Python.'.format(_ANTLR3_REV))

    output_dir = self._create_package_structure(target_workdir, target.module)

    java_main = 'org.antlr.Tool'
    args = ['-fo', output_dir]
    antlr_classpath = self.tool_classpath('antlr3')
    sources = self._calculate_sources([target])
    args.extend(sources)
    result = self.runjava(classpath=antlr_classpath, main=java_main, args=args,
                          workunit_name='antlr')
    if result != 0:
      raise TaskError('java {} ... exited non-zero ({})'.format(java_main, result))

  def _calculate_sources(self, targets):
    sources = set()

    def collect_sources(tgt):
      if self.is_gentarget(tgt):
        sources.update(tgt.sources_relative_to_buildroot())
    for target in targets:
      target.walk(collect_sources)
    return sources

  # Antlr3 doesn't create the package structure, so we have to do so, and then tell
  # it where to write the files.
  def _create_package_structure(self, workdir, module):
    path = workdir
    for d in module.split('.'):
      path = os.path.join(path, d)
      # Supposedly we get handed a clean workdir, but I'm not sure that's true.
      safe_mkdir(path, clean=True)
      touch(os.path.join(path, '__init__.py'))
    return path
