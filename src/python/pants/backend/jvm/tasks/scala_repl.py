# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from twitter.common.collections import OrderedSet

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
  def select_targets(cls, target):
    return isinstance(target, (JarLibrary, JvmTarget))

  def setup_repl_session(self, targets):
    return self.classpath(targets, classpath_prefix=self.tool_classpath('scala-repl'))

  def launch_repl(self, classpath):
    # The scala repl requires -Dscala.usejavacp=true since Scala 2.8 when launching in the way
    # we do here (not passing -classpath as a program arg to scala.tools.nsc.MainGenericRunner).
    jvm_options = self.jvm_options
    if not any(opt.startswith('-Dscala.usejavacp=') for opt in jvm_options):
      jvm_options.append('-Dscala.usejavacp=true')

    # NOTE: We execute with no workunit, as capturing REPL output makes it very sluggish.
    #
    # NOTE: Disable creating synthetic jar here because the classLoader used by REPL
    # does not load Class-Path from manifest.
    DistributionLocator.cached().execute_java(classpath=classpath,
                                              main=self.get_options().main,
                                              jvm_options=jvm_options,
                                              args=self.args,
                                              create_synthetic_jar=False)
