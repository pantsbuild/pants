# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.tasks.jvmdoc_gen import Jvmdoc, JvmdocGen


scaladoc = Jvmdoc(tool_name='scaladoc', product_type='scaladoc')


def is_scala(target):
  return target.has_sources('.scala')


class ScaladocGen(JvmdocGen):
  @classmethod
  def setup_parser(cls, option_group, args, mkflag):
    cls.generate_setup_parser(option_group, args, mkflag, scaladoc)

  def __init__(self, context, workdir, confs=None, active=True):
    super(ScaladocGen, self).__init__(context, workdir, scaladoc, confs, active)

  def execute(self):
    self.generate_execute(lambda t: t.is_scala, create_scaladoc_command)


def create_scaladoc_command(classpath, gendir, *targets):
  sources = []
  for target in targets:
    sources.extend(target.sources_relative_to_buildroot())
    # TODO(Tejal Desai): pantsbuild/pants/65: Remove java_sources attribute for ScalaLibrary
    for java_target in target.java_sources:
      sources.extend(java_target.sources_relative_to_buildroot())

  if not sources:
    return None

  # TODO(John Chee): try scala.tools.nsc.ScalaDoc via ng
  command = [
    'scaladoc',
    '-usejavacp',
    '-classpath', ':'.join(classpath),
    '-d', gendir,
  ]

  command.extend(sources)
  return command
