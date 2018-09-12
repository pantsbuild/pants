# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import os
from builtins import object
from hashlib import sha1

from future.utils import text_type

from pants.backend.jvm.subsystems.dependency_context import DependencyContext
from pants.backend.jvm.subsystems.java import Java
from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.targets.scala_jar_dependency import ScalaJarDependency
from pants.backend.jvm.tasks.classpath_products import ClasspathEntry
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.base.build_environment import get_buildroot
from pants.base.workunit import WorkUnitLabel
from pants.engine.fs import DirectoryToMaterialize, PathGlobs, PathGlobsAndRoot
from pants.engine.isolated_process import ExecuteProcessRequest
from pants.java.jar.jar_dependency import JarDependency
from pants.subsystem.subsystem import Subsystem
from pants.util.dirutil import fast_relpath
from pants.util.memo import memoized_method, memoized_property


class Zinc(object):
  """Configuration for Pants' zinc wrapper tool."""

  ZINC_COMPILE_MAIN = 'org.pantsbuild.zinc.compiler.Main'
  ZINC_BOOTSTRAPER_MAIN = 'org.pantsbuild.zinc.bootstrapper.Main'
  ZINC_EXTRACT_MAIN = 'org.pantsbuild.zinc.extractor.Main'
  DEFAULT_CONFS = ['default']

  ZINC_COMPILER_TOOL_NAME = 'zinc'
  ZINC_BOOTSTRAPPER_TOOL_NAME = 'zinc-bootstrapper'
  ZINC_EXTRACTOR_TOOL_NAME = 'zinc-extractor'

  class Factory(Subsystem, JvmToolMixin):
    options_scope = 'zinc'

    @classmethod
    def subsystem_dependencies(cls):
      return super(Zinc.Factory, cls).subsystem_dependencies() + (DependencyContext,
                                                                  Java,
                                                                  ScalaPlatform)

    @classmethod
    def register_options(cls, register):
      super(Zinc.Factory, cls).register_options(register)

      zinc_rev = '1.0.3'

      shader_rules = [
          # The compiler-interface and compiler-bridge tool jars carry xsbt and
          # xsbti interfaces that are used across the shaded tool jar boundary so
          # we preserve these root packages wholesale along with the core scala
          # APIs.
          Shader.exclude_package('scala', recursive=True),
          Shader.exclude_package('xsbt', recursive=True),
          Shader.exclude_package('xsbti', recursive=True),
          # Unfortunately, is loaded reflectively by the compiler.
          Shader.exclude_package('org.apache.logging.log4j', recursive=True),
        ]

      cls.register_jvm_tool(register,
                            Zinc.ZINC_BOOTSTRAPPER_TOOL_NAME,
                            classpath=[
                              JarDependency('org.pantsbuild', 'zinc-bootstrapper_2.11', '0.0.2'),
                            ],
                            main=Zinc.ZINC_BOOTSTRAPER_MAIN,
                            custom_rules=shader_rules,
                          )

      cls.register_jvm_tool(register,
                            Zinc.ZINC_COMPILER_TOOL_NAME,
                            classpath=[
                              JarDependency('org.pantsbuild', 'zinc-compiler_2.11', '0.0.8'),
                            ],
                            main=Zinc.ZINC_COMPILE_MAIN,
                            custom_rules=shader_rules)

      cls.register_jvm_tool(register,
                            'compiler-bridge',
                            classpath=[
                              ScalaJarDependency(org='org.scala-sbt',
                                                name='compiler-bridge',
                                                rev=zinc_rev,
                                                classifier='sources',
                                                intransitive=True),
                            ])

      cls.register_jvm_tool(register,
                            'compiler-interface',
                            classpath=[
                              JarDependency(org='org.scala-sbt',
                                            name='compiler-interface',
                                            rev=zinc_rev),
                            ],
                            # NB: We force a noop-jarjar'ing of the interface, since it is now
                            # broken up into multiple jars, but zinc does not yet support a sequence
                            # of jars for the interface.
                            main='no.such.main.Main',
                            custom_rules=shader_rules)

      cls.register_jvm_tool(register,
                            Zinc.ZINC_EXTRACTOR_TOOL_NAME,
                            classpath=[
                              JarDependency('org.pantsbuild', 'zinc-extractor_2.11', '0.0.6')
                            ])

      # Register tools for fixed versions of Scala, 2.10, 2.11 and 2.12.
      # Relies on ScalaPlatform to get the revision version from the major.minor version.
      # The tool with the correct scala version will be retrieved later,
      # taking the user-passed option into account.
      def register_scala_tools_for_versions(tools, scala_versions):
        for tool_name in tools:
          for scala_version in scala_versions:
            cls.register_jvm_tool(register,
                                  ScalaPlatform.versioned_tool_name(tool_name, scala_version),
                                  classpath=[
                                    ScalaPlatform
                                      .create_jardep(tool_name, scala_version)
                                      .copy(intransitive=True)
                                  ])

      register_scala_tools_for_versions(
        tools=["scala-compiler", "scala-library", "scala-reflect"],
        scala_versions=["2.10", "2.11", "2.12"]
      )

    @classmethod
    def _zinc(cls, products):
      return cls.tool_jar_from_products(products, Zinc.ZINC_COMPILER_TOOL_NAME, cls.options_scope)

    @classmethod
    def _compiler_bridge(cls, products):
      return cls.tool_jar_from_products(products, 'compiler-bridge', cls.options_scope)

    @classmethod
    def _compiler_interface(cls, products):
      return cls.tool_jar_from_products(products, 'compiler-interface', cls.options_scope)

    @classmethod
    def _compiler_bootstrapper(cls, products):
      return cls.tool_jar_from_products(products, Zinc.ZINC_BOOTSTRAPPER_TOOL_NAME, cls.options_scope)

    # Retrieves the path of a tool's jar
    # by looking at the classpath of the registered tool with the user-specified scala version.
    def _fetch_tool_jar_from_classpath(self, products, tool_name):
      scala_version = ScalaPlatform.global_instance().version
      classpath = self.tool_classpath_from_products(products,
                                                    ScalaPlatform.versioned_tool_name(tool_name, scala_version),
                                                    scope=self.options_scope)
      assert(len(classpath) == 1)
      return classpath[0]

    def _scala_compiler(self, products):
      return self._fetch_tool_jar_from_classpath(products, 'scala-compiler')

    def _scala_library(self, products):
      return self._fetch_tool_jar_from_classpath(products, 'scala-library')

    def _scala_reflect(self, products):
      return self._fetch_tool_jar_from_classpath(products, 'scala-reflect')

    def create(self, products):
      """Create a Zinc instance from products active in the current Pants run.

      :param products: The active Pants run products to pluck classpaths from.
      :type products: :class:`pants.goal.products.Products`
      :returns: A Zinc instance with access to relevant Zinc compiler wrapper jars and classpaths.
      :rtype: :class:`Zinc`
      """
      return Zinc(self, products)

  def __init__(self, zinc_factory, products):
    self._zinc_factory = zinc_factory
    self._products = products

  @memoized_property
  def zinc(self):
    """Return the Zinc wrapper compiler classpath.

    :rtype: list of str
    """
    return self._zinc_factory._zinc(self._products)

  @property
  def dist(self):
    """Return the distribution selected for Zinc.

    :rtype: list of str
    """
    return self._zinc_factory.dist

  @memoized_property
  def compiler_bridge(self):
    """Return the path to the Zinc compiler-bridge jar.

    :rtype: str
    """
    return self._zinc_factory._compiler_bridge(self._products)

  @memoized_property
  def compiler_interface(self):
    """Return the path to the Zinc compiler-interface jar.

    :rtype: str
    """
    return self._zinc_factory._compiler_interface(self._products)

  @memoized_property
  def scala_compiler(self):
    """Return the path to the scala compiler jar.

    :rtype: str
    """
    return self._zinc_factory._scala_compiler(self._products)

  @memoized_property
  def scala_library(self):
    """Return the path to the scala library jar (runtime).

    :rtype: str
    """
    return self._zinc_factory._scala_library(self._products)

  @memoized_property
  def scala_reflect(self):
    """Return the path to the scala library jar (runtime).

    :rtype: str
    """
    return self._zinc_factory._scala_reflect(self._products)

  @memoized_property
  def _compiler_bridge_cache_dir(self):
    """A directory where we can store compiled copies of the `compiler-bridge`.

    The compiler-bridge is specific to each scala version.
    Currently we compile the `compiler-bridge` only once, while bootstrapping.
    Then, we store it in the working directory under .pants.d/zinc/<cachekey>, where
    <cachekey> is calculated using the locations of zinc, the compiler interface,
    and the compiler bridge.
    """
    hasher = sha1()
    for cp_entry in [self.zinc, self.compiler_interface, self.compiler_bridge]:
      hasher.update(os.path.relpath(cp_entry, get_buildroot()))
    key = hasher.hexdigest()[:12]

    return os.path.join(self._zinc_factory.get_options().pants_workdir, 'zinc', 'compiler-bridge', key)

  def _make_relative(self, path):
    """A utility function to create relative paths to the work dir"""
    return fast_relpath(path, get_buildroot())

  def compile_compiler_bridge(self, context):
    """Compile the compiler bridge to be used by zinc, using our scala bootstrapper.
    It will compile and cache the jar, and materialize it if not already there.

    :param context: The context of the task trying to compile the bridge.
                    This is mostly needed to use its scheduler to create digests of the relevant jars.
    :return: The absolute path to the compiled scala-compiler-bridge jar.
    """
    bridge_jar = os.path.join(self._compiler_bridge_cache_dir, 'scala-compiler-bridge.jar')
    is_executing_remotely = context.options.for_global_scope().remote_execution_server

    if is_executing_remotely or not os.path.exists(bridge_jar):
      bootstrapper = self._zinc_factory._compiler_bootstrapper(self._products)
      bootstrapper_args = [
        "--out", bridge_jar,
        "--compiler-interface", self.compiler_interface,
        "--compiler-bridge-src", self.compiler_bridge,
        "--scala-compiler", self.scala_compiler,
        "--scala-library", self.scala_library,
        "--scala-reflect", self.scala_reflect,
      ]
      input_jar_snapshots = context._scheduler.capture_snapshots((PathGlobsAndRoot(
        PathGlobs(tuple([self._make_relative(jar) for jar in bootstrapper_args[1::2]])),
        text_type(get_buildroot())
      ),))
      argv = tuple(['.jdk/bin/java'] +
                   ['-cp', bootstrapper, Zinc.ZINC_BOOTSTRAPER_MAIN] +
                   bootstrapper_args
      )
      req = ExecuteProcessRequest(
        argv=argv,
        input_files=input_jar_snapshots[0].directory_digest,
        output_files=(self._make_relative(bridge_jar),),
        output_directories=(self._make_relative(self._compiler_bridge_cache_dir),),
        description="bootstrap compiler bridge.",
        jdk_home=self.dist.home,
      )
      res = context.execute_process_synchronously_or_raise(req, 'zinc-subsystem', [WorkUnitLabel.COMPILER])
      if not is_executing_remotely:
        context._scheduler.materialize_directories((
          DirectoryToMaterialize(get_buildroot(), res.output_directory_digest),
        ))
    return bridge_jar

  @memoized_method
  def snapshot(self, scheduler):
    buildroot = get_buildroot()
    return scheduler.capture_snapshots((
      PathGlobsAndRoot(
        PathGlobs(
          tuple(
            fast_relpath(a, buildroot)
              for a in (self.zinc, self.compiler_bridge, self.compiler_interface)
          )
        ),
        buildroot,
      ),
    ))[0]

  # TODO: Make rebase map work without needing to pass in absolute paths:
  # https://github.com/pantsbuild/pants/issues/6434
  @memoized_property
  def rebase_map_args(self):
    """We rebase known stable paths in zinc analysis to make it portable across machines."""
    rebases = {
        self.dist.real_home: '/dev/null/remapped_by_pants/java_home/',
        get_buildroot(): '/dev/null/remapped_by_pants/buildroot/',
        self._zinc_factory.get_options().pants_workdir: '/dev/null/remapped_by_pants/workdir/',
      }
    return (
        '-rebase-map',
        ','.join('{}:{}'.format(src, dst) for src, dst in rebases.items())
      )

  @memoized_method
  def _compiler_plugins_cp_entries(self):
    """Any additional global compiletime classpath entries for compiler plugins."""
    java_options_src = Java.global_instance()
    scala_options_src = ScalaPlatform.global_instance()

    def cp(instance, toolname):
      scope = instance.options_scope
      return instance.tool_classpath_from_products(self._products, toolname, scope=scope)
    classpaths = (cp(java_options_src, 'javac-plugin-dep') +
                  cp(scala_options_src, 'scalac-plugin-dep'))
    return [(conf, ClasspathEntry(jar)) for conf in self.DEFAULT_CONFS for jar in classpaths]

  @memoized_property
  def extractor(self):
    return self._zinc_factory.tool_classpath_from_products(self._products,
                                                           self.ZINC_EXTRACTOR_TOOL_NAME,
                                                           scope=self._zinc_factory.options_scope)

  def compile_classpath_entries(self, classpath_product_key, target, extra_cp_entries=None):
    classpath_product = self._products.get_data(classpath_product_key)
    if DependencyContext.global_instance().defaulted_property(target, lambda x: x.strict_deps):
      dependencies = target.strict_dependencies(DependencyContext.global_instance())
    else:
      dependencies = DependencyContext.global_instance().all_dependencies(target)

    all_extra_cp_entries = list(self._compiler_plugins_cp_entries())
    if extra_cp_entries:
      all_extra_cp_entries.extend(extra_cp_entries)

    # TODO: We convert dependencies to an iterator here in order to _preserve_ a bug that will be
    # fixed in https://github.com/pantsbuild/pants/issues/4874: `ClasspathUtil.compute_classpath`
    # expects to receive a list, but had been receiving an iterator. In the context of an
    # iterator, `excludes` are not applied
    # in ClasspathProducts.get_product_target_mappings_for_targets.
    return ClasspathUtil.compute_classpath_entries(iter(dependencies),
      classpath_product,
      all_extra_cp_entries,
      self.DEFAULT_CONFS,
    )

  def compile_classpath(self, classpath_product_key, target, extra_cp_entries=None):
    """Compute the compile classpath for the given target."""
    return list(
      entry.path
        for entry in self.compile_classpath_entries(classpath_product_key, target, extra_cp_entries)
    )
