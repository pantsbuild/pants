# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import namedtuple

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.subsystems.zinc_language_mixin import ZincLanguageMixin
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.build_graph.address import Address
from pants.build_graph.injectables_mixin import InjectablesMixin
from pants.java.jar.jar_dependency import JarDependency
from pants.subsystem.subsystem import Subsystem


# full_version - the full scala version to use.
major_version_info = namedtuple('major_version_info', ['full_version'])


# Note that the compiler has two roles here: as a tool (invoked by the compile task), and as a
# runtime library (when compiling plugins, which require the compiler library as a dependency).
scala_build_info = {
  '2.10': major_version_info(full_version='2.10.6'),
  '2.11': major_version_info(full_version='2.11.12'),
  '2.12': major_version_info(full_version='2.12.10'),
}


# Because scalastyle inspects only the sources, it needn't match the platform version.
scala_style_jar = JarDependency('org.scalastyle', 'scalastyle_2.11', '0.8.0')


# TODO: Sort out JVM compile config model: https://github.com/pantsbuild/pants/issues/4483.
class ScalaPlatform(JvmToolMixin, ZincLanguageMixin, InjectablesMixin, Subsystem):
  """A scala platform.

  :API: public
  """
  options_scope = 'scala'

  @classmethod
  def create_jardep(cls, name, version):
    return JarDependency(org='org.scala-lang',
                         name=name,
                         rev=scala_build_info[version].full_version)

  @classmethod
  def _create_runtime_jardep(cls, version):
    return cls.create_jardep('scala-library', version)

  @classmethod
  def _create_compiler_jardep(cls, version):
    return cls.create_jardep('scala-compiler', version)

  @classmethod
  def versioned_tool_name(cls, tool, version):
    if version == 'custom':
      return tool
    else:
      return '{}_{}'.format(tool, version.replace('.', '_'))

  @classmethod
  def register_options(cls, register):
    def register_scala_compiler_tool(version):
      cls.register_jvm_tool(register,
                            cls.versioned_tool_name('scalac', version),
                            classpath=[cls._create_compiler_jardep(version)])

    def register_scala_repl_tool(version, with_jline=False):
      classpath = [cls._create_compiler_jardep(version)]  # Note: the REPL is in the compiler jar.
      if with_jline:
        jline_dep = JarDependency(
            org = 'org.scala-lang',
            name = 'jline',
            rev = scala_build_info[version].full_version
        )
        classpath.append(jline_dep)
      cls.register_jvm_tool(register,
                            cls.versioned_tool_name('scala-repl', version),
                            classpath=classpath)

    def register_style_tool(version):
      cls.register_jvm_tool(register,
                            cls.versioned_tool_name('scalastyle', version),
                            classpath=[scala_style_jar])

    super().register_options(register)

    register('--scalac-plugins', advanced=True, type=list, fingerprint=True,
            help='Use these scalac plugins.')
    register('--scalac-plugin-args', advanced=True, type=dict, default={}, fingerprint=True,
            help='Map from scalac plugin name to list of arguments for that plugin.')
    cls.register_jvm_tool(register, 'scalac-plugin-dep', classpath=[],
                        help='Search for scalac plugins here, as well as in any '
                                'explicit dependencies.')

    register('--version', advanced=True, default='2.12',
             choices=['2.10', '2.11', '2.12', 'custom'], fingerprint=True,
             help='The scala platform version. If --version=custom, the targets '
                  '//:scala-library, //:scalac, //:scala-repl and //:scalastyle will be used, '
                  'and must exist.  Otherwise, defaults for the specified version will be used.')

    register('--suffix-version', advanced=True, default=None,
             help='Scala suffix to be used in `scala_jar` definitions. For example, specifying '
                  '`2.11` or `2.12.0-RC1` would cause `scala_jar` lookups for artifacts with '
                  'those suffixes.')

    # Register the fixed version tools.
    register_scala_compiler_tool('2.10')
    register_scala_repl_tool('2.10', with_jline=True)  # 2.10 repl requires jline.
    register_style_tool('2.10')

    register_scala_compiler_tool('2.11')
    register_scala_repl_tool('2.11')
    register_style_tool('2.11')

    register_scala_compiler_tool('2.12')
    register_scala_repl_tool('2.12')
    register_style_tool('2.12')

    # Register the custom tools. We provide a dummy classpath, so that register_jvm_tool won't
    # require that a target with the given spec actually exist (not everyone will define custom
    # scala platforms). However if the custom tool is actually resolved, we want that to
    # fail with a useful error, hence the dummy jardep with rev=None.
    def register_custom_tool(key):
      dummy_jardep = JarDependency('missing spec', ' //:{}'.format(key))
      cls.register_jvm_tool(register, cls.versioned_tool_name(key, 'custom'),
                            classpath=[dummy_jardep])
    register_custom_tool('scalac')
    register_custom_tool('scala-repl')
    register_custom_tool('scalastyle')

  def _tool_classpath(self, tool, products):
    """Return the proper classpath based on products and scala version."""
    return self.tool_classpath_entries_from_products(
        products,
        self.versioned_tool_name(tool, self.version),
        scope=self.options_scope,
      )

  def compiler_classpath_entries(self, products):
    """Returns classpath entries for the scalac tool."""
    return self._tool_classpath('scalac', products)

  def style_classpath(self, products):
    """Returns classpath as paths for scalastyle."""
    classpath_entries = self._tool_classpath('scalastyle', products)
    return [classpath_entry.path for classpath_entry in classpath_entries]

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
        raise RuntimeError('Suffix version must be specified if using a custom scala version. '
                           'Suffix version is used for bootstrapping jars.  If a custom '
                           'scala version is not specified, then the version specified in '
                           '--scala-suffix-version is used.  For example for Scala '
                           '2.10.7 you would use the suffix version "2.10".')

    elif name.endswith(self.version):
      raise ValueError('The name "{0}" should not be suffixed with the scala platform version '
                      '({1}): it will be added automatically.'.format(name, self.version))
    return '{0}_{1}'.format(name, self.version)

  @property
  def repl(self):
    """Return the repl tool key."""
    return self.versioned_tool_name('scala-repl', self.version)

  def injectables(self, build_graph):
    if self.version == 'custom':
      return

    specs_to_create = [
      ('scalac', self._create_compiler_jardep),
      ('scala-library', self._create_runtime_jardep)
    ]

    for spec_key, create_jardep_func in specs_to_create:
      spec = self.injectables_spec_for_key(spec_key)
      target_address = Address.parse(spec)
      if not build_graph.contains_address(target_address):
        jars = [create_jardep_func(self.version)]
        build_graph.inject_synthetic_target(target_address,
                                           JarLibrary,
                                           jars=jars,
                                           scope='forced')
      elif not build_graph.get_target(target_address).is_synthetic:
        raise build_graph.ManualSyntheticTargetError(target_address)

  @property
  def injectables_spec_mapping(self):
    maybe_suffix = '' if self.version == 'custom' else '-synthetic'
    return {
      # Target spec for the scala compiler library.
      'scalac': ['//:scalac{}'.format(maybe_suffix)],
      # Target spec for the scala runtime library.
      'scala-library': ['//:scala-library{}'.format(maybe_suffix)]
    }
