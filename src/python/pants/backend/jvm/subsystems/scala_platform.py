# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.subsystems.zinc_language_mixin import ZincLanguageMixin
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.build_graph.address import Address
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized


major_version_info = namedtuple(major_version_info, 'full_version compiler_name runtime_name')
scala_build_info = {
  '2.10': major_version_info('2.10.4', 'scalac_2_10', 'runtime_2_10'),
  '2.11': major_version_info('2.11.7', 'scalac_2_11', 'runtime_2_11'),
}

class ScalaPlatform(JvmToolMixin, ZincLanguageMixin, Subsystem):
  """A scala platform.

  TODO: Rework so there's a way to specify a default as direct pointers to jar coordinates,
  so we don't require specs in BUILD.tools if the default is acceptable.
  """
  options_scope = 'scala-platform'

  runtime_2_10 = JarDependency(org = 'org.scala-lang',
                               name = 'scala-library',
                               rev = scala_build_info['2.10'].full_version)

  runtime_2_11 = JarDependency(org = 'org.scala-lang',
                               name = 'scala-library',
                               rev = scala_build_info['2.11'].full_version)

  runtime_default = '//:scala-library'

  @classmethod
  def register_options(cls, register):
    super(ScalaPlatform, cls).register_options(register)
    # Version specified will allow the user provide some sane defaults for common
    # versions of scala. If version is something other than one of the common
    # versions the user will be able to overrride the defaults by specifying
    # custom build targets for //:scalac and //:scala-library
    register('--version', advanced=True, default='2.10',
             help='The scala "platform version", which is suffixed onto all published '
                  'libraries. This should match the declared compiler/library versions.')

    # Scala 2.10
    cls.register_jvm_tool(register,
                          'scalac_2_10',
                          classpath=[
                            JarDependency(org = 'org.scala-lang',
                                          name = 'scala-compiler',
                                          rev = scala_build_info['2.10'].full_version),
                          ])


    # Scala 2.11
    cls.register_jvm_tool(register,
                          'scalac_2_11',
                          classpath=[
                            JarDependency(org = 'org.scala-lang',
                                          name = 'scala-compiler',
                                          rev = scala_build_info['2.11'].full_version),
                          ])

    # Provide a default so that if scala-compiler since all jvm tools are bootstrapped.
    cls.register_jvm_tool(register,
                          'scalac',
                          classpath=[
                            JarDependency(org = 'org.scala-lang',
                                          name = 'scala-compiler',
                                          rev = scala_build_info['2.10'].full_version),
                          ])

  def compiler_classpath(self, products):
    """Return the proper classpath based on products and scala version."""
    compiler_name = scala_build_info.get(self.get_options().version, scalac)
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
    """Return the proper runtime based on scala version.
    :return iterator: list with single runtime.
    """
    runtime_name = scala_build_info.get(self.get_options().version, 'runtime_default')
    return [getattr(self, runtime_name)]


  @classmethod
  @memoized
  def _synthetic_runtime_target(cls, buildgraph):
    resource_address = Address.parse('//:scala-library')
    if not buildgraph.contains_address(resource_address):
      runtime = ScalaPlatform.global_instance().runtime
      buildgraph.inject_synthetic_target(resource_address, JarLibrary,
                                               derived_from=cls,
                                               jars=runtime)

    return buildgraph.get_target(resource_address)
