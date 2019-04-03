# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.tasks.jvmdoc_gen import Jvmdoc, JvmdocGen
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.util.memo import memoized


MAX_ARG_STRLEN = 131072


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
    tool_classpath = [cp_entry.path for cp_entry in scala_platform.compiler_classpath_entries(
      self.context.products, self.context._scheduler)]

    args = ['-usejavacp',
            '-classpath', ':'.join(classpath),
            '-d', gendir]

    args.extend(self.args)

    args.extend(sources)

    # Check the size of the ScalaDoc command arguments, and use a options file if too long.
    #
    # There are a couple practical limits to consider.
    #
    # - The length of any individual value must be less than MAX_ARG_STRLEN
    #   which is hardcoded to 131072 bytes.
    #
    # - The total length of the command must be less than the OS's `getconf ARG_MAX`
    #   value.
    #
    #   This value will vary by system. For exmaple, on my MacOS 10.13.6 Twitter-issued
    #   developer laptop this value is currently 262144. Doing some research on the
    #   internet shows a wide range of default values for this ranging from 131072 to
    #   2097152 (2MB). Unfortunately, there doesn't seem to be an easy way to query the
    #   system for this value. It's not in sysconfig.get_config_vars, or posix.environ,
    #   or os.environ. We could shell out to `getconf` to get the actual value, but
    #   anecdotal evidence suggests that there are other layers of limits beyond just
    #   this POSIX value. POSIX requires ARG_MAX to be at least 4096 bytes, but it's
    #   extremely unlikely to find a system with that low setting. Rather, I think a
    #   practical middle ground would be the MAX_ARG_STRLEN fixed value.
    #
    #   So, given that rationale, if the arg list is longer than MAX_ARG_STRLEN
    #   we should put it in an external file, just in case.

    args_joined = ' '.join(map(str, args))
    if len(args_joined) > MAX_ARG_STRLEN:
      self.context.log.debug("ScalaDoc arguments too long. Using options file.")

      # dump to file, overwriting any file that already exists
      options_filepath = os.path.join(self.workdir, 'scaladoc_options.txt')
      with open(options_filepath, 'w') as filehandle:
        filehandle.write(args_joined)

      args = ['@{}'.format(options_filepath)]

    java_executor = SubprocessExecutor(DistributionLocator.cached())
    runner = java_executor.runner(jvm_options=self.jvm_options,
                                  classpath=tool_classpath,
                                  main='scala.tools.nsc.ScalaDoc',
                                  args=args)

    self.context.log.debug("SCALADOCS COMMAND: {}".format(runner.command))
    return runner.command
