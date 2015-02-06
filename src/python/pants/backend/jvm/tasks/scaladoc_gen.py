# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.jvmdoc_gen import Jvmdoc, JvmdocGen


scaladoc = Jvmdoc(tool_name='scaladoc', product_type='scaladoc')


def is_scala(target):
  return target.has_sources('.scala')


class ScaladocGen(JvmdocGen):
  @classmethod
  def jvmdoc(cls):
    return scaladoc

  def execute(self):
    self.generate_doc(lambda t: t.is_scala, self.create_scaladoc_command)

  def create_scaladoc_command(self, classpath, gendir, *targets):
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

    for jvm_option in self.jvm_options:
      if jvm_option.startswith('-D'):
        command.append(jvm_option)  # Scaladoc takes sysprop settings directly.
      else:
        command.append('-J{0}'.format(jvm_option))

    command.extend(self.args)

    command.extend(sources)
    return command
