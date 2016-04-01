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
  'full_version compiler_name runtime_name repl_name style_name style_version')

scala_build_info = {
  '2.10':
    major_version_info(
      full_version='2.10.4',
      compiler_name='scalac_2_10',
      runtime_name='runtime_2_10',
      repl_name='scala_2_10_repl',
      style_name='scalastyle_2_10',
      style_version='0.3.2'),
  '2.11':
    major_version_info(
      full_version='2.11.7',
      compiler_name='scalac_2_11',
      runtime_name='runtime_2_11',
      repl_name='scala_2_11_repl',
      style_name='scalastyle_2_11',
      style_version='0.8.0'),
  'custom':
    major_version_info(
      full_version=None,
      compiler_name='scalac',
      runtime_name='runtime_default',
      repl_name='scala_repl',
      style_name='scalastyle',
      style_version=None),
}


class ScalaPlatform(JvmToolMixin, ZincLanguageMixin, Subsystem):
  """A scala platform.

  :API: public
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
    def _register_tool(org, dep_name, name, version, extra_deps=None):
      classpaths = [JarDependency(org=org, name=dep_name, rev=version)]
      if extra_deps:
        classpaths.extend(extra_deps)

      cls.register_jvm_tool(register, name, classpath=classpaths)

    def register_scala_compiler(version):
      name = scala_build_info[version].compiler_name
      version = scala_build_info[version].full_version
      _register_tool('org.scala-lang', 'scala-compiler', name, version)

    def register_scala_repl(version, extra_deps=None):
      name, version = scala_build_info[version].repl_name, scala_build_info[version].full_version
      _register_tool('org.scala-lang', 'scala-compiler', name, version, extra_deps)

    def register_style_tool(version):
      # Note: Since we can't use ScalaJarDependency without creating a import loop we need to
      # specify the version info in the name.
      name = scala_build_info[version].style_name
      style_version = scala_build_info[version].style_version
      _register_tool('org.scalastyle', 'scalastyle_{}'.format(version), name, style_version)

    super(ScalaPlatform, cls).register_options(register)
    register('--version', advanced=True, default='2.10',
             choices=['2.10', '2.11', 'custom'], fingerprint=True,
             help='The scala "platform version", which is suffixed onto all published '
                  'libraries. This should match the declared compiler/library versions. '
                  'Version specified will allow the user provide some sane defaults for common '
                  'versions of scala. If version is something other than one of the common '
                  'versions the user will be able to override the defaults by specifying '
                  '"custom" as the --version, custom build targets can be specified in the targets '
                  'for //:scalac and //:scala-library ')

    register('--runtime-spec', advanced=True, default='//:scala-library',
             help='Address to be used for custom scala runtime.')

    register('--repl-spec', advanced=True, default='//:scala-repl',
             help='Address to be used for custom scala runtime.')

    register('--suffix-version', advanced=True, default=None,
             help='Scala suffix to be used when a custom version is specified.  For example 2.10')

    # Register Scala compilers.
    register_scala_compiler('2.10')
    register_scala_compiler('2.11')
    register_scala_compiler('custom')

    # Register repl tools.
    jline_dep = JarDependency(
        org = 'org.scala-lang',
        name = 'jline',
        rev = scala_build_info['2.10'].full_version
    )  # Dep is only used by scala 2.10.x

    register_scala_repl('2.10', extra_deps=[jline_dep])
    register_scala_repl('2.11')
    register_scala_repl('custom', extra_deps=[jline_dep])

    # Register Scala style libraries.
    register_style_tool('2.10')
    register_style_tool('2.11')
    register_style_tool('custom')

  def _get_label(self):
    return getattr(self.get_options(), 'version', 'custom')

  def compiler_classpath(self, products):
    """Return the proper classpath based on products and scala version."""
    compiler_name = scala_build_info.get(self._get_label()).compiler_name
    return self.tool_classpath_from_products(products, compiler_name, scope=self.options_scope)

  def style_classpath(self, products):
    """Return the proper classpath based on products and scala version."""
    style_name = scala_build_info.get(self._get_label()).style_name
    return self.tool_classpath_from_products(products, style_name, scope=self.options_scope)

  @property
  def version(self):
    return self.get_options().version

  def suffix_version(self, name):
    """Appends the platform version to the given artifact name.

    Also validates that the name doesn't already end with the version.
    """
    if self._get_label() == 'custom':
      suffix = self.get_options().suffix_version
      if suffix:
        return '{0}_{1}'.format(name, suffix)
      else:
        raise RuntimeError('Suffix version must be specified if using a custom scala version.'
                           'Suffix version is used for bootstrapping jars.  If a custom '
                           'scala version is not specified, then the version specified in '
                           '--scala-platform-suffix-version is used.  For example for Scala '
                           '2.10.7 you would use the suffix version "2.10"'
              )

    if name.endswith(self.version):
      raise ValueError('The name "{0}" should not be suffixed with the scala platform version '
                      '({1}): it will be added automatically.'.format(name, self.version))
    return '{0}_{1}'.format(name, self.version)

  @property
  def repl(self):
    """Return the proper repl name.
    :return iterator: list with single runtime.
    """
    if self.get_options().version == 'custom':
      return self.get_options().repl_spec
    else:
      return scala_build_info.get(self._get_label()).repl_name

  @property
  def runtime(self):
    """Return the proper runtime based on scala version.
    :return iterator: list with single runtime.
    """
    # If the version is custom allow the user the option to set the spec.
    if self._get_label() == 'custom':
      return [self.get_options().runtime_spec]
    else:
      runtime_name = scala_build_info.get(self._get_label()).runtime_name
      return [getattr(self, runtime_name)]

  @classmethod
  def _synthetic_runtime_target(cls, buildgraph):
    """Insert synthetic target for scala runtime into the buildgraph
    :param pants.build_graph.build_graph.BuildGraph buildgraph: buildgraph object
    :return pants.build_graph.address.Address:
    """
    # If a custom runtime is specified return it instead of synthetic target
    # This will pull in user defined scala-library defs
    custom_runtime_spec = ScalaPlatform.global_instance().runtime[0]

    if ScalaPlatform.global_instance().version == 'custom':
      return custom_runtime_spec
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
      return buildgraph.get_target(synth_library_address).address.spec
