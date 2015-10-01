# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.core.tasks.repl_task_mixin import ReplTaskMixin
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.backend.jvm.tasks.jvm_task import JvmTask
from pants.backend.jvm.tasks.jvm_tool_task_mixin import JvmToolTaskMixin
from pants.java.distribution.distribution import DistributionLocator


class ScalaRepl(JvmToolTaskMixin, ReplTaskMixin, JvmTask):
  @classmethod
  def register_options(cls, register):
    super(ScalaRepl, cls).register_options(register)
    register('--main', default='scala.tools.nsc.MainGenericRunner',
             help='The entry point for running the repl.')
    cls.register_jvm_tool(register, 'scala-repl', classpath_spec='//:scala-repl')

  @classmethod
  def subsystem_dependencies(cls):
    return super(ScalaRepl, cls).subsystem_dependencies() + (DistributionLocator,)

  @classmethod
  def prepare(cls, options, round_manager):
    super(ScalaRepl, cls).prepare(options, round_manager)

    # TODO(John Sirois): these are fake requirements in order to force compile run before this
    # goal. Introduce a RuntimeClasspath product for JvmCompile and PrepareResources to populate
    # and depend on that.
    # See: https://github.com/pantsbuild/pants/issues/310
    round_manager.require_data('resources_by_target')
    round_manager.require_data('classes_by_target')

  @classmethod
  def select_targets(cls, target):
    return isinstance(target, (JarLibrary, JvmTarget))

  def setup_repl_session(self, targets):
    tools_classpath = self.tool_classpath('scala-repl')
    return self.classpath(targets, classpath_prefix=tools_classpath)

  def launch_repl(self, classpath):
    # The scala repl requires -Dscala.usejavacp=true since Scala 2.8 when launching in the way
    # we do here (not passing -classpath as a program arg to scala.tools.nsc.MainGenericRunner).
    jvm_options = self.jvm_options
    if not any(opt.startswith('-Dscala.usejavacp=') for opt in jvm_options):
      jvm_options.append('-Dscala.usejavacp=true')

    # NOTE: We execute with no workunit, as capturing REPL output makes it very sluggish.
    DistributionLocator.cached().execute_java(classpath=classpath,
                                              main=self.get_options().main,
                                              jvm_options=jvm_options,
                                              args=self.args)
