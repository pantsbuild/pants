# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.java.distribution.distribution import DistributionLocator
from pants.task.repl_task_mixin import ReplTaskMixin


class ScalaRepl(JvmToolTaskMixin, ReplTaskMixin, JvmTask):
  _RUNNER_MAIN = 'org.pantsbuild.tools.runner.PantsRunner'

  @classmethod
  def register_options(cls, register):
    super(ScalaRepl, cls).register_options(register)
    register('--main', default='scala.tools.nsc.MainGenericRunner',
             help='The entry point for running the repl.')
    cls.register_jvm_tool(register, 'scala-repl', classpath_spec='//:scala-repl')
    cls.register_jvm_tool(register, 'pants-runner', classpath=[
        JarDependency(org='org.pantsbuild', name='pants-runner', rev='0.0.1'),
    ], main=ScalaRepl._RUNNER_MAIN)

  @classmethod
  def subsystem_dependencies(cls):
    return super(ScalaRepl, cls).subsystem_dependencies() + (DistributionLocator,)

  @classmethod
  def select_targets(cls, target):
    return isinstance(target, (JarLibrary, JvmTarget))

  def setup_repl_session(self, targets):
    return self.tool_classpath('pants-runner') + self.tool_classpath('scala-repl') +\
           self.classpath(targets)

  def launch_repl(self, classpath):
    # The scala repl requires -Dscala.usejavacp=true since Scala 2.8 when launching in the way
    # we do here (not passing -classpath as a program arg to scala.tools.nsc.MainGenericRunner).
    jvm_options = self.jvm_options
    if not any(opt.startswith('-Dscala.usejavacp=') for opt in jvm_options):
      jvm_options.append('-Dscala.usejavacp=true')

    # NOTE: We execute with no workunit, as capturing REPL output makes it very sluggish.
    #
    # NOTE: Using PantsRunner class because the classLoader used by REPL
    # does not load Class-Path from manifest.
    DistributionLocator.cached().execute_java(classpath=classpath,
                                              main=ScalaRepl._RUNNER_MAIN,
                                              jvm_options=jvm_options,
                                              args=[self.get_options().main] + self.args,
                                              create_synthetic_jar=True)
