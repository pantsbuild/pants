# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from abc import abstractmethod

from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.backend.jvm.tasks.rewrite_base import RewriteBase
from pants.base.exceptions import TaskError
from pants.build_graph.build_graph import BuildGraph
from pants.build_graph.target_scopes import Scopes
from pants.java.jar.jar_dependency import JarDependency
from pants.option.custom_types import file_option
from pants.task.fmt_task_mixin import FmtTaskMixin
from pants.task.lint_task_mixin import LintTaskMixin
from pants.util.memo import memoized_property


class ScalaFix(RewriteBase):
  """Executes the scalafix tool."""

  _SCALAFIX_MAIN = 'scalafix.cli.Cli'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--configuration', type=file_option, default=None, fingerprint=True,
             help='The config file to use (in HOCON format).')
    register('--rules', default='ProcedureSyntax', type=str, fingerprint=True,
             help='The `rules` arg to scalafix: generally a name like `ProcedureSyntax`.')
    register('--semantic', type=bool, default=False, fingerprint=True,
             help='True to enable `semantic` scalafix rules by requesting compilation and '
                  'providing the target classpath to scalafix. To enable this option, you '
                  'will need to install the `semanticdb-scalac` compiler plugin. See '
                  'https://www.pantsbuild.org/scalac_plugins.html for more information.')
    cls.register_jvm_tool(register,
                          'scalafix',
                          classpath=[
                            JarDependency(org='ch.epfl.scala', name='scalafix-cli_2.12.8', rev='0.9.4'),
                          ])
    cls.register_jvm_tool(register, 'scalafix-tool-classpath', classpath=[])

  @classmethod
  def target_types(cls):
    return ['scala_library', 'junit_tests', 'java_tests']

  @classmethod
  def source_extension(cls):
    return '.scala'

  @classmethod
  def prepare(cls, options, round_manager):
    super().prepare(options, round_manager)
    # Only request a classpath and zinc_args if semantic checks are enabled.
    if options.semantic:
      round_manager.require_data('zinc_args') 
      round_manager.require_data('runtime_classpath')

  @memoized_property
  def _scalac_args(self):
    if self.get_options().semantic:
      targets = self.context.targets()
      targets_to_zinc_args = self.context.products.get_data('zinc_args')
      
      for t in targets:
        zinc_args = targets_to_zinc_args[t]
        args = []
        for arg in zinc_args:
          arg = arg.strip()
          if arg.startswith('-S'):
            args.append(arg[2:])
        # All targets will get the same scalac args
        if args:
          return args

    return []

  @staticmethod
  def _compute_classpath(runtime_classpath, targets):
    closure = BuildGraph.closure(targets, bfs=True,
                                 include_scopes=Scopes.JVM_RUNTIME_SCOPES, respect_intransitive=True)
    classpath_for_targets = ClasspathUtil.classpath(closure, runtime_classpath)

    return classpath_for_targets

  def invoke_tool(self, absolute_root, target_sources):
    args = []
    tool_classpath = self.tool_classpath('scalafix-tool-classpath')
    if tool_classpath:
      args.append('--tool-classpath={}'.format(os.pathsep.join(tool_classpath)))
    if self.get_options().semantic:
      # If semantic checks are enabled, we need the full classpath for these targets.
      runtime_classpath = self.context.products.get_data('runtime_classpath')
      classpath = ScalaFix._compute_classpath(runtime_classpath, {target for target, _ in target_sources})
      args.append('--sourceroot={}'.format(absolute_root))
      args.append('--classpath={}'.format(os.pathsep.join(classpath)))
    if self.get_options().configuration:
      args.append('--config={}'.format(self.get_options().configuration))
    if self.get_options().rules:
      args.append('--rules={}'.format(self.get_options().rules))
    if self.get_options().level == 'debug':
      args.append('--verbose')

    # This is how you pass a list of strings to a single arg key
    for a in self._scalac_args:
      args.append('--scalac-options')
      args.append(a)
      
    args.extend(self.additional_args or [])

    args.extend(source for _, source in target_sources)

    # Execute.
    return self.runjava(classpath=self.tool_classpath('scalafix'),
                        main=self._SCALAFIX_MAIN,
                        jvm_options=self.get_options().jvm_options,
                        args=args,
                        workunit_name='scalafix')

  @property
  @abstractmethod
  def additional_args(self):
    """Additional arguments to the Scalafix command."""


class ScalaFixFix(FmtTaskMixin, ScalaFix):
  """Applies fixes generated by scalafix."""

  sideeffecting = True
  additional_args = []

  def process_result(self, result):
    if result != 0:
      raise TaskError(
          '{main} ... failed to fix ({result}) targets.'.format(
            main=self._SCALAFIX_MAIN,
            result=result))


class ScalaFixCheck(LintTaskMixin, ScalaFix):
  """Checks whether any fixes were generated by scalafix."""

  sideeffecting = False
  additional_args = ['--test']

  def process_result(self, result):
    if result != 0:
      raise TaskError('Targets failed scalafix checks.'.format())
