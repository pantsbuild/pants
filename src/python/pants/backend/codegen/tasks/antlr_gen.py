# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging
import os
import re

from pants.backend.codegen.targets.java_antlr_library import JavaAntlrLibrary
from pants.backend.codegen.tasks.simple_codegen_task import SimpleCodegenTask
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.backend.jvm.tasks.nailgun_task import NailgunTask
from pants.base.exceptions import TaskError


logger = logging.getLogger(__name__)


def antlr4_jar(name):
  return JarDependency(org='org.antlr', name=name, rev='4.1')


_DEFAULT_ANTLR_DEPS = {
  'antlr3': ('//:antlr-3.4', [JarDependency(org='org.antlr', name='antlr', rev='3.4')]),
  'antlr4': ('//:antlr-4', [antlr4_jar(name='antlr4'),
                            antlr4_jar(name='antlr4-runtime')])
}


class AntlrGen(SimpleCodegenTask, NailgunTask):

  class AmbiguousPackageError(TaskError):
    """Raised when a java package cannot be unambiguously determined for a JavaAntlrLibrary."""

  class AntlrIsolatedCodegenStrategy(SimpleCodegenTask.IsolatedCodegenStrategy):
    def find_sources(self, target):
      sources = super(AntlrGen.AntlrIsolatedCodegenStrategy, self).find_sources(target)
      return [source for source in sources if source.endswith('.java')]

  @classmethod
  def register_options(cls, register):
    super(AntlrGen, cls).register_options(register)
    for key, (classpath_spec, classpath) in _DEFAULT_ANTLR_DEPS.items():
      cls.register_jvm_tool(register, key, classpath=classpath, classpath_spec=classpath_spec)

  def is_gentarget(self, target):
    return isinstance(target, JavaAntlrLibrary)

  def synthetic_target_type(self, target):
    return JavaLibrary

  @classmethod
  def supported_strategy_types(cls):
    return [cls.AntlrIsolatedCodegenStrategy]

  def execute_codegen(self, targets):
    for target in targets:
      args = ['-o', self.codegen_workdir(target)]
      compiler = target.compiler
      if compiler == 'antlr3':
        if target.package is not None:
          logger.warn("The 'package' attribute is not supported for antlr3 and will be ignored.")
        java_main = 'org.antlr.Tool'
      elif compiler == 'antlr4':
        args.append('-visitor')  # Generate Parse Tree Visitor As Well
        # Note that this assumes that there is no package set in the antlr file itself,
        # which is considered an ANTLR best practice.
        args.append('-package')
        if target.package is None:
          args.append(self._get_sources_package(target))
        else:
          args.append(target.package)
        java_main = 'org.antlr.v4.Tool'

      antlr_classpath = self.tool_classpath(compiler)
      sources = self._calculate_sources([target])
      args.extend(sources)
      result = self.runjava(classpath=antlr_classpath, main=java_main, args=args,
                            workunit_name='antlr')
      if result != 0:
        raise TaskError('java {} ... exited non-zero ({})'.format(java_main, result))

      if compiler == 'antlr3':
        for source in list(self.codegen_strategy.find_sources(target)):
          self._scrub_generated_timestamp(source)

  def synthetic_target_extra_dependencies(self, target):
    # Fetch the right java dependency from the target's compiler option
    compiler_classpath_spec = self.get_options()[target.compiler]
    return self.resolve_deps([compiler_classpath_spec])

  # This checks to make sure that all of the sources have an identical package source structure, and
  # if they do, uses that as the package. If they are different, then the user will need to set the
  # package as it cannot be correctly inferred.
  def _get_sources_package(self, target):
    parents = set([os.path.dirname(source) for source in target.sources_relative_to_source_root()])
    if len(parents) != 1:
      raise self.AmbiguousPackageError('Antlr sources in multiple directories, cannot infer '
                                       'package. Please set package member in antlr target.')
    return parents.pop().replace('/', '.')

  def _calculate_sources(self, targets):
    sources = set()

    def collect_sources(target):
      if self.is_gentarget(target):
        sources.update(target.sources_relative_to_buildroot())
    for target in targets:
      target.walk(collect_sources)
    return sources

  _COMMENT_WITH_TIMESTAMP_RE = re.compile('^//.*\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d')

  def _scrub_generated_timestamp(self, source):
    # Removes the first line of comment if it contains a timestamp.
    with open(source) as f:
      lines = f.readlines()
    if len(lines) < 1:
      return
    with open(source, 'w') as f:
      if not self._COMMENT_WITH_TIMESTAMP_RE.match(lines[0]):
        f.write(lines[0])
      for line in lines[1:]:
        f.write(line)
