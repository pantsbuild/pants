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


# full_version - the full scala version to use.
# style_version - the version of org.scalastyle.scalastyle to use.
major_version_info = namedtuple('major_version_info', ['full_version', 'style_version'])


# Note that the compiler has two roles here: as a tool (invoked by the compile task), and as a
# runtime library (when compiling plugins, which require the compiler library as a dependency).
scala_build_info = {
  '2.10':
    major_version_info(
      full_version='2.10.4',
      style_version='0.3.2'),
  '2.11':
    major_version_info(
      full_version='2.11.7',
      style_version='0.8.0'),
}


class ScalaPlatform(JvmToolMixin, ZincLanguageMixin, Subsystem):
  """A scala platform.

  :API: public
  """
  options_scope = 'scala-platform'

  @classmethod
  def _create_jardep(cls, name, version):
    return JarDependency(org='org.scala-lang',
                         name=name,
                         rev=scala_build_info[version].full_version)

  @classmethod
  def _create_runtime_jardep(cls, version):
    return cls._create_jardep('scala-library', version)

  @classmethod
  def _create_compiler_jardep(cls, version):
    return cls._create_jardep('scala-compiler', version)

  @classmethod
  def _key_for_tool_version(cls, tool, version):
    if version == 'custom':
      return tool
    else:
      return '{}_{}'.format(tool, version.replace('.', '_'))

  @classmethod
  def register_options(cls, register):
    def register_scala_compiler_tool(version):
      cls.register_jvm_tool(register,
                            cls._key_for_tool_version('scalac', version),
                            classpath=[cls._create_compiler_jardep(version)])

    def register_scala_repl_tool(version, with_jline=False):
      classpath = [cls._create_compiler_jardep(version)]  # Note: the REPL is in the compiler jar.
      if with_jline:
        jline_dep = JarDependency(
            org = 'org.scala-lang',
            name = 'jline',
            rev = scala_build_info['2.10'].full_version
        )
        classpath.append(jline_dep)
      cls.register_jvm_tool(register,
                            cls._key_for_tool_version('scala-repl', version),
                            classpath=classpath)

    def register_style_tool(version):
      # Note: Since we can't use ScalaJarDependency without creating a import loop we need to
      # specify the version info in the name.
      style_version = scala_build_info[version].style_version
      jardep = JarDependency('org.scalastyle', 'scalastyle_{}'.format(version), style_version)
      cls.register_jvm_tool(register,
                            cls._key_for_tool_version('scalastyle', version),
                            classpath=[jardep])

    super(ScalaPlatform, cls).register_options(register)
    register('--version', advanced=True, default='2.10',
             choices=['2.10', '2.11', 'custom'], fingerprint=True,
             help='The scala platform version. If --version=custom, the targets '
                  '//:scala-library, //:scalac, //:scala-repl and //:scalastyle will be used, '
                  'and must exist.  Otherwise, defaults for the specified version will be used.')

    register('--suffix-version', advanced=True, default=None,
             help='Scala suffix to be used when a custom version is specified.  For example 2.10.')

    # Register the fixed version tools.
    register_scala_compiler_tool('2.10')
    register_scala_repl_tool('2.10', with_jline=True)  # 2.10 repl requires jline.
    register_style_tool('2.10')

    register_scala_compiler_tool('2.11')
    register_scala_repl_tool('2.11')
    register_style_tool('2.11')

    # Register the custom tools. We provide a dummy classpath, so that register_jvm_tool won't
    # require that a target with the given spec actually exist (not everyone will define custom
    # scala platforms). However if the custom tool is actually resolved, we want that to
    # fail with a useful error, hence the dummy jardep with rev=None.
    def register_custom_tool(key):
      dummy_jardep = JarDependency('missing spec', ' //:{}'.format(key))
      cls.register_jvm_tool(register, cls._key_for_tool_version(key, 'custom'),
                            classpath=[dummy_jardep])
    register_custom_tool('scalac')
    register_custom_tool('scala-repl')
    register_custom_tool('scalastyle')

  def _tool_classpath(self, tool, products):
    """Return the proper classpath based on products and scala version."""
    return self.tool_classpath_from_products(products,
                                             self._key_for_tool_version(tool, self.version),
                                             scope=self.options_scope)

  def compiler_classpath(self, products):
    return self._tool_classpath('scalac', products)

  def style_classpath(self, products):
    return self._tool_classpath('scalastyle', products)

  @property
  def version(self):
    return self.get_options().version

  def suffix_version(self, name):
    """Appends the platform version to the given artifact name.

    Also validates that the name doesn't already end with the version.
    """
    if self.version == 'custom':
      suffix = self.get_options().suffix_version
      if suffix:
        return '{0}_{1}'.format(name, suffix)
      else:
        raise RuntimeError('Suffix version must be specified if using a custom scala version.'
                           'Suffix version is used for bootstrapping jars.  If a custom '
                           'scala version is not specified, then the version specified in '
                           '--scala-platform-suffix-version is used.  For example for Scala '
                           '2.10.7 you would use the suffix version "2.10".')

    elif name.endswith(self.version):
      raise ValueError('The name "{0}" should not be suffixed with the scala platform version '
                      '({1}): it will be added automatically.'.format(name, self.version))
    return '{0}_{1}'.format(name, self.version)

  @property
  def repl(self):
    """Return the repl tool key."""
    return self._key_for_tool_version('scala-repl', self.version)

  @classmethod
  def compiler_library_target_spec(cls, buildgraph):
    """Returns a target spec for the scala compiler library.

    Synthesizes one into the buildgraph if necessary.

    :param pants.build_graph.build_graph.BuildGraph buildgraph: buildgraph object.
    :return a target spec:
    """
    return ScalaPlatform.global_instance()._library_target_spec(buildgraph, 'scalac',
                                                                cls._create_compiler_jardep)

  @classmethod
  def runtime_library_target_spec(cls, buildgraph):
    """Returns a target spec for the scala runtime library.

    Synthesizes one into the buildgraph if necessary.

    :param pants.build_graph.build_graph.BuildGraph buildgraph: buildgraph object.
    :return a target spec:
    """
    return ScalaPlatform.global_instance()._library_target_spec(buildgraph, 'scala-library',
                                                                cls._create_runtime_jardep)

  def _library_target_spec(self, buildgraph, key, create_jardep_func):
    if self.version == 'custom':
      return '//:{}'.format(key)
    else:
      synthetic_address = Address.parse('//:{}-synthetic'.format(key))
      if not buildgraph.contains_address(synthetic_address):
        jars = [create_jardep_func(self.version)]
        buildgraph.inject_synthetic_target(synthetic_address, JarLibrary, jars=jars, scope='forced')
      elif not buildgraph.get_target(synthetic_address).is_synthetic:
        raise buildgraph.ManualSyntheticTargetError(synthetic_address)
      return buildgraph.get_target(synthetic_address).address.spec
