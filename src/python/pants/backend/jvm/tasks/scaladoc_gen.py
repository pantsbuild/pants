# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.tasks.jvmdoc_gen import Jvmdoc, JvmdocGen
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.util.memo import memoized


class ScaladocGen(JvmdocGen):
  """Generate scaladoc html for Scala source targets."""

  @classmethod
  @memoized
  def jvmdoc(cls):
    return Jvmdoc(tool_name='scaladoc', product_type='scaladoc')

  @classmethod
  def subsystem_dependencies(cls):
    return super(ScaladocGen, cls).subsystem_dependencies() + (DistributionLocator, ScalaPlatform.scoped(cls))

  @classmethod
  def prepare(cls, options, round_manager):
    super(ScaladocGen, cls).prepare(options, round_manager)
    ScalaPlatform.prepare_tools(round_manager)

  def execute(self):
    def is_scala(target):
      return target.has_sources('.scala')

    self.generate_doc(is_scala, self.create_scaladoc_command)

  def create_scaladoc_command(self, classpath, gendir, *targets):
    sources = []
    for target in targets:
      sources.extend(target.sources_relative_to_buildroot())
      # TODO(Tejal Desai): pantsbuild/pants/65: Remove java_sources attribute for ScalaLibrary
      # A '.scala' owning target may not have java_sources, eg: junit_tests
      if hasattr(target, 'java_sources'):
        for java_target in target.java_sources:
          sources.extend(java_target.sources_relative_to_buildroot())

    if not sources:
      return None

    scala_platform = ScalaPlatform.global_instance()
    tool_classpath = scala_platform.compiler_classpath(self.context.products)

    args = ['-usejavacp',
            '-classpath', ':'.join(classpath),
            '-d', gendir]

    args.extend(self.args)

    args.extend(sources)

    java_executor = SubprocessExecutor(DistributionLocator.cached())
    runner = java_executor.runner(jvm_options=self.jvm_options,
                                  classpath=tool_classpath,
                                  main='scala.tools.nsc.ScalaDoc',
                                  args=args)
    return runner.command
