# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.subsystems.zinc_language_mixin import ZincLanguageMixin
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.subsystem.subsystem import Subsystem


SCALA_211 = '2.11.7'
SCALA_210 = '2.10.4'


class ScalaPlatform(JvmToolMixin, ZincLanguageMixin, Subsystem):
  """A scala platform.

  TODO: Rework so there's a way to specify a default as direct pointers to jar coordinates,
  so we don't require specs in BUILD.tools if the default is acceptable.
  """
  options_scope = 'scala-platform'

  runtime_2_10 = JarDependency(org = 'org.scala-lang',
                               name = 'scala-library',
                               rev = SCALA_210)

  runtime_2_11 = JarDependency(org = 'org.scala-lang',
                               name = 'scala-library',
                               rev = SCALA_211)

  runtime_default = '//:scala-library'

  @classmethod
  def register_options(cls, register):
    super(ScalaPlatform, cls).register_options(register)
    # No need to fingerprint --runtime, because it is automatically inserted as a
    # dependency for the scala_library target.

    register('--version', advanced=True, default='2.10',
             help='The scala "platform version", which is suffixed onto all published '
                  'libraries. This should match the declared compiler/library versions.')

    # Scala 2.10
    cls.register_jvm_tool(register,
                          'scalac_2_10',
                          classpath=[
                            JarDependency(org = 'org.scala-lang',
                                          name = 'scala-compiler',
                                          rev = SCALA_210),
                          ])


    # Scala 2.11
    cls.register_jvm_tool(register,
                          'scalac_2_11',
                          classpath=[
                            JarDependency(org = 'org.scala-lang',
                                          name = 'scala-compiler',
                                          rev = SCALA_211),
                          ])

    # Scala Default if scala-compiler isn't specified and no version was specified.
    cls.register_jvm_tool(register,
                          'scalac',
                          classpath=[
                            JarDependency(org = 'org.scala-lang',
                                          name = 'scala-compiler',
                                          rev = SCALA_210),
                          ])

  def compiler_classpath(self, products):
    """ Return the proper classpath based on products and scala version. """
    compiler_name = {
      '2.10': 'scalac_2_10',
      '2.11': 'scalac_2_11',
    }.get(self.get_options().version, 'scalac')
    return self.tool_classpath_from_products(products, compiler_name, scope=self.options_scope)

  @property
  def version(self):
    return self.get_options().version

  def suffix_version(self, name):
    """Appends the platform version to the given artifact name.

    Also validates that the name doesn't already end with the version.
    """
    if name.endswith(self.version):
      raise ValueError('The name "{0}" should not be suffixed with the scala platform version '
                      '({1}): it will be added automatically.'.format(name, self.version))
    return '{0}_{1}'.format(name, self.version)

  @property
  def runtime(self):
    """ Return the proper runtime based on scala version.
    :return iterator: list with single runtime.
    """
    runtime_name = {
      '2.11': 'runtime_2_11',
      '2.10': 'runtime_2_10',
      'runtime_default': 'runtime_default',
    }.get(self.get_options().version, 'runtime_default')
    return [getattr(self, runtime_name)]
