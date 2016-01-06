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


major_version_info = namedtuple(
  'major_version_info',
  'full_version compiler_name runtime_name repl_name')

scala_build_info = {
  '2.10': major_version_info('2.10.4', 'scalac_2_10', 'runtime_2_10', 'scala_2_10_repl'),
  '2.11': major_version_info('2.11.7', 'scalac_2_11', 'runtime_2_11', 'scala_2_11_repl'),
  'custom': major_version_info(None, 'scalac', 'runtime_default', 'scala-repl'),
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
    # versions the user will be able to override the defaults by specifying
    # custom build targets for //:scalac and //:scala-library
    register('--version', advanced=True, default='2.10', choices=['2.10', '2.11', 'custom'],
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

    # Provide a classpath default for scala-compiler since all jvm tools are bootstrapped.
    cls.register_jvm_tool(register,
                          'scalac',
                          classpath=[
                            JarDependency(org = 'org.scala-lang',
                                          name = 'scala-compiler',
                                          rev = scala_build_info['2.10'].full_version),
                          ])

    # Scala 2.10 repl
    cls.register_jvm_tool(register,
                          'scala_2_10_repl',
                          classpath=[
                            JarDependency(org = 'org.scala-lang',
                                          name = 'jline',
                                          rev = scala_build_info['2.10'].full_version),
                            JarDependency(org = 'org.scala-lang',
                                          name = 'scala-compiler',
                                          rev = scala_build_info['2.10'].full_version),
                          ])

    # Scala 2.11 repl
    cls.register_jvm_tool(register,
                          'scala_2_11_repl',
                          classpath=[
                            JarDependency(org = 'org.scala-lang',
                                          name = 'jline',
                                          rev = scala_build_info['2.11'].full_version),
                            JarDependency(org = 'org.scala-lang',
                                          name = 'scala-compiler',
                                          rev = scala_build_info['2.11'].full_version),
                          ])

    # Provide a classpath default for scala-repl since all jvm tools are bootstrapped.
    cls.register_jvm_tool(register,
                          'scala_repl',
                          classpath=[
                            JarDependency(org = 'org.scala-lang',
                                          name = 'jline',
                                          rev = scala_build_info['2.10'].full_version),
                            JarDependency(org = 'org.scala-lang',
                                          name = 'scala-compiler',
                                          rev = scala_build_info['2.10'].full_version),
                          ])

  def _get_label(self):
    return getattr(self.get_options(), 'version', 'custom')

  def compiler_classpath(self, products):
    """Return the proper classpath based on products and scala version."""
    compiler_name = scala_build_info.get(self._get_label()).compiler_name
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
  def repl(self):
    """Return the proper repl name.
    :return iterator: list with single runtime.
    """
    return scala_build_info.get(self._get_label()).repl_name

  @property
  def runtime(self):
    """Return the proper runtime based on scala version.
    :return iterator: list with single runtime.
    """
    runtime_name = scala_build_info.get(self._get_label()).runtime_name
    return [getattr(self, runtime_name)]

  @classmethod
  def _synthetic_runtime_target(cls, buildgraph):
    """Insert synthetic target for scala runtime into the buildgraph
    :param pants.build_graph.build_graph.BuildGraph buildgraph: buildgraph object
    :return pants.build_graph.address.Address:
    """
    # If scala-library is already defined return it instead of synthetic target
    # This will pull in user defined scala-library defs
    library_address = Address.parse('//:scala-library')
    if buildgraph.contains_address(library_address):
      return buildgraph.get_target(library_address)
    else:
      # Create an address for the synthetic target if needed
      synth_library_address = Address.parse('//:scala_library_synthetic')
      if not buildgraph.contains_address(synth_library_address):
        runtime = ScalaPlatform.global_instance().runtime
        buildgraph.inject_synthetic_target(synth_library_address,
                                           JarLibrary,
                                           jars=runtime)
      else:
        if not buildgraph.get_target(synth_library_address).is_synthetic:
          raise buildgraph.ManualSyntheticTargetError(
            'Synthetic targets can not be defined manually'
          )
      return buildgraph.get_target(synth_library_address)
