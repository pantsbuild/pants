# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from collections import namedtuple
from contextlib import contextmanager

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.tasks.classpath_util import ClasspathUtil
from pants.java.distribution.distribution import DistributionLocator
from pants.java.executor import SubprocessExecutor
from pants.java.jar.jar_dependency import JarDependency
from pants.subsystem.subsystem import Subsystem, SubsystemError
from pants.util.contextutil import temporary_file


class UnaryRule(namedtuple('UnaryRule', ['name', 'pattern'])):
  """Base class for shading keep and zap rules specifiable in BUILD files."""

  def render(self):
    return '{name} {pattern}\n'.format(name=self.name, pattern=self.pattern)


class RelocateRule(namedtuple('Rule', ['from_pattern', 'to_pattern'])):
  """Base class for shading relocation rules specifiable in BUILD files."""

  _wildcard_pattern = re.compile('[*]+')
  _starts_with_number_pattern = re.compile('^[0-9]')
  _illegal_package_char_pattern = re.compile('[^a-z0-9_]', re.I)

  @classmethod
  def _infer_shaded_pattern_iter(cls, from_pattern, prefix=None):
    if prefix:
      yield prefix
    last = 0
    for i, match in enumerate(cls._wildcard_pattern.finditer(from_pattern)):
      yield from_pattern[last:match.start()]
      yield '@{}'.format(i+1)
      last = match.end()
    yield from_pattern[last:]

  @classmethod
  def new(cls, from_pattern, shade_pattern=None, shade_prefix=None):
    if not shade_pattern:
      shade_pattern = ''.join(cls._infer_shaded_pattern_iter(from_pattern, shade_prefix))
    return cls(from_pattern, shade_pattern)

  def render(self):
    return 'rule {0} {1}\n'.format(self.from_pattern, self.to_pattern)


class Shading(object):
  """Wrapper around relocate and exclude shading rules exposed in BUILD files."""

  SHADE_PREFIX = '__shaded_by_pants__.'
  """The default shading package."""

  @classmethod
  def create_keep(cls, pattern):
    """Creates a rule which marks classes matching the given pattern as roots.

    If any keep rules are set, all classes that are not reachable from roots are removed from the
    jar.

    Examples: ::

        # Only include classes reachable from Main.
        shading_keep('org.foobar.example.Main')

        # Only keep classes reachable from the example package.
        shading_keep('org.foobar.example.*')

    :param string pattern: Any fully-qualified classname which matches this pattern will be kept as
      a root. '*' is a wildcard that matches any individual package component, and '**' is a
      wildcard that matches any trailing pattern (ie the rest of the string).
    """
    return UnaryRule('keep', pattern)

  @classmethod
  def create_zap(cls, pattern):
    """Creates a rule which removes matching classes from the jar.

    Examples: ::

        # Remove the main class.
        shading_zap('org.foobar.example.Main')

        # Remove everything in the example package.
        shading_keep('org.foobar.example.*')

    :param string pattern: Any fully-qualified classname which matches this pattern will removed
      from the jar. '*' is a wildcard that matches any individual package component, and '**' is a
      wildcard that matches any trailing pattern (ie the rest of the string).
    """
    return UnaryRule('zap', pattern)

  @classmethod
  def create_relocate(cls, from_pattern, shade_pattern=None, shade_prefix=None):
    """Creates a rule which shades jar entries from one pattern to another.

    Examples: ::

        # Rename everything in the org.foobar.example package
        # to __shaded_by_pants__.org.foobar.example.
        shading_relocate('org.foobar.example.**')

        # Rename org.foobar.example.Main to __shaded_by_pants__.org.foobar.example.Main
        shading_relocate('org.foobar.example.Main')

        # Rename org.foobar.example.Main to org.foobar.example.NotMain
        shading_relocate('org.foobar.example.Main', 'org.foobar.example.NotMain')

        # Rename all 'Main' classes under any direct subpackage of org.foobar.
        shading_relocate('org.foobar.*.Main')

        # Rename org.foobar package to com.barfoo package
        shading_relocate('org.foobar.**', 'com.barfoo.@1')

        # Rename everything in org.foobar.example package to __hello__.org.foobar.example
        shading_relocate('org.foobar.example.**', shade_prefix='__hello__')

    :param string from_pattern: Any fully-qualified classname which matches this pattern will be
      shaded. '*' is a wildcard that matches any individual package component, and '**' is a
      wildcard that matches any trailing pattern (ie the rest of the string).
    :param string shade_pattern: The shaded pattern to use, where ``@1``, ``@2``, ``@3``, etc are
      references to the groups matched by wildcards (groups are numbered from left to right). If
      omitted, this pattern is inferred from the input pattern, prefixed by the ``shade_prefix``
      (if provided). (Eg, a ``from_pattern`` of ``com.*.foo.bar.**`` implies a default
      ``shade_pattern`` of ``__shaded_by_pants__.com.@1.foo.@2``)
    :param string shade_prefix: Prefix to prepend when generating a ``shade_pattern`` (if a
      ``shade_pattern`` is not provided by the user). Defaults to '``__shaded_by_pants__.``'.
    """
    # NB(gmalmquist): Have have to check "is None" rather than using an or statement, because the
    # empty-string is a valid prefix which should not be replaced by the default prefix.
    shade_prefix = Shading.SHADE_PREFIX if shade_prefix is None else shade_prefix
    return RelocateRule.new(from_pattern, shade_pattern, shade_prefix)

  @classmethod
  def create_exclude(cls, pattern):
    """Creates a rule which excludes the given pattern from shading.

    Examples: ::

        # Don't shade the org.foobar.example.Main class
        shading_exclude('org.foobar.example.Main')

        # Don't shade anything under org.foobar.example
        shading_exclude('org.foobar.example.**')

    :param string pattern: Any fully-qualified classname which matches this pattern will NOT be
      shaded. '*' is a wildcard that matches any individual package component, and '**' is a
      wildcard that matches any trailing pattern (ie the rest of the string).
    """
    return cls.create_relocate(pattern, shade_prefix='')

  @classmethod
  def create_keep_package(cls, package_name, recursive=True):
    """Convenience constructor for a package keep rule.

    Essentially equivalent to just using ``shading_keep('package_name.**')``.

    :param string package_name: Package name to keep (eg, ``org.pantsbuild.example``).
    :param bool recursive: Whether to keep everything under any subpackage of ``package_name``,
      or just direct children of the package. (Defaults to True).
    """
    return cls.create_keep(cls._format_package_glob(package_name, recursive))

  @classmethod
  def create_zap_package(cls, package_name, recursive=True):
    """Convenience constructor for a package zap rule.

    Essentially equivalent to just using ``shading_zap('package_name.**')``.

    :param string package_name: Package name to remove (eg, ``org.pantsbuild.example``).
    :param bool recursive: Whether to remove everything under any subpackage of ``package_name``,
      or just direct children of the package. (Defaults to True).
    """
    return cls.create_zap(cls._format_package_glob(package_name, recursive))

  @classmethod
  def create_relocate_package(cls, package_name, shade_prefix=None, recursive=True):
    """Convenience constructor for a package relocation rule.

    Essentially equivalent to just using ``shading_relocate('package_name.**')``.

    :param string package_name: Package name to shade (eg, ``org.pantsbuild.example``).
    :param string shade_prefix: Optional prefix to apply to the package. Defaults to
      ``__shaded_by_pants__.``.
    :param bool recursive: Whether to rename everything under any subpackage of ``package_name``,
      or just direct children of the package. (Defaults to True).
    """
    return cls.create_relocate(from_pattern=cls._format_package_glob(package_name, recursive),
                               shade_prefix=shade_prefix)

  @classmethod
  def create_exclude_package(cls, package_name, recursive=True):
    """Convenience constructor for a package exclusion rule.

    Essentially equivalent to just using ``shading_exclude('package_name.**')``.

    :param string package_name: Package name to exclude (eg, ``org.pantsbuild.example``).
    :param bool recursive: Whether to exclude everything under any subpackage of ``package_name``,
      or just direct children of the package. (Defaults to True).
    """
    return cls.create_relocate(from_pattern=cls._format_package_glob(package_name, recursive),
                               shade_prefix='')

  @classmethod
  def _format_package_glob(cls, package_name, recursive=True):
    return '{package}.{capture}'.format(package=package_name, capture='**' if recursive else '*')


class Shader(object):
  """Creates shaded jars."""

  class Error(Exception):
    """Indicates an error shading a jar."""

  class Factory(JvmToolMixin, Subsystem):
    options_scope = 'shader'

    class Error(SubsystemError):
      """Error creating a Shader with the Shader.Factory subsystem."""

    @classmethod
    def subsystem_dependencies(cls):
      return super(Shader.Factory, cls).subsystem_dependencies() + (DistributionLocator,)

    @classmethod
    def register_options(cls, register):
      super(Shader.Factory, cls).register_options(register)
      cls.register_jvm_tool(register,
                            'jarjar',
                            classpath=[
                              JarDependency(org='org.pantsbuild', name='jarjar', rev='1.6.4')
                            ])

    @classmethod
    def create(cls, context, executor=None):
      """Creates and returns a new Shader.

      :param Executor executor: Optional java executor to run jarjar with.
      """
      if executor is None:
        executor = SubprocessExecutor(DistributionLocator.cached())
      classpath = cls.global_instance().tool_classpath_from_products(context.products, 'jarjar',
                                                                     cls.options_scope)
      return Shader(classpath, executor)

  @classmethod
  def exclude_package(cls, package_name=None, recursive=False):
    """Excludes the given fully qualified package name from shading.

    :param unicode package_name: A fully qualified package_name; eg: `org.pantsbuild`; `None` for
                                the java default (root) package.
    :param bool recursive: `True` to exclude any package with `package_name` as a proper prefix;
                           `False` by default.
    :returns: A `Shader.Rule` describing the shading exclusion.
    """
    if not package_name:
      return Shading.create_exclude('**' if recursive else '*')
    return Shading.create_exclude_package(package_name, recursive=recursive)

  @classmethod
  def exclude_class(cls, class_name):
    """Excludes the given fully qualified class name from shading.

    :param unicode class_name: A fully qualified classname, eg: `org.pantsbuild.tools.jar.Main`.
    :returns: A `Shader.Rule` describing the shading exclusion.
    """
    return Shading.create_exclude(class_name)

  @classmethod
  def shade_package(cls, package_name=None, recursive=False):
    """Includes the given fully qualified package name in shading.

    :param unicode package_name: A fully qualified package_name; eg: `org.pantsbuild`; `None` for
                                 the java default (root) package.
    :param bool recursive: `True` to include any package with `package_name` as a proper prefix;
                           `False` by default.
    :returns: A `Shader.Rule` describing the packages to be shaded.
    """
    if not package_name:
      return Shading.create_relocate('**' if recursive else '*')
    return Shading.create_relocate_package(package_name, recursive=recursive)

  @classmethod
  def shade_class(cls, class_name):
    """Includes the given fully qualified class in shading.

    :param unicode class_name: A fully qualified classname, eg: `org.pantsbuild.tools.jar.Main`.
    :returns: A `Shader.Rule` describing the class shading.
    """
    return Shading.create_relocate(class_name)

  @staticmethod
  def _iter_packages(paths):
    for path in paths:
      yield path.replace('/', '.')

  @staticmethod
  def _potential_package_path(path):
    # TODO(John Sirois): Implement a full valid java package name check, `-` just happens to get
    # the common non-package cases like META-INF/...
    return path.endswith('.class') or path.endswith('.java') and '-' not in path

  @classmethod
  def _iter_dir_packages(cls, path):
    paths = set()
    for root, dirs, files in os.walk(path):
      for filename in files:
        if cls._potential_package_path(filename):
          package_path = os.path.dirname(os.path.join(root, filename))
          paths.add(os.path.relpath(package_path, path))
    return cls._iter_packages(paths)

  @classmethod
  def _iter_jar_packages(cls, path):
    paths = set()
    for pathname in ClasspathUtil.classpath_entries_contents([path]):
      if cls._potential_package_path(pathname):
        paths.add(os.path.dirname(pathname))
    return cls._iter_packages(paths)

  def __init__(self, jarjar_classpath, executor):
    """Creates a `Shader` the will use the given `jarjar` jar to create shaded jars.

    :param jarjar_classpath: The jarjar classpath.
    :type jarjar_classpath: list of string.
    :param executor: A java `Executor` to use to create shaded jar files.
    """
    self._jarjar_classpath = jarjar_classpath
    self._executor = executor
    self._system_packages = None

  def _calculate_system_packages(self):
    system_packages = set()
    boot_classpath = self._executor.distribution.system_properties['sun.boot.class.path']
    for path in boot_classpath.split(os.pathsep):
      if os.path.exists(path):
        if os.path.isdir(path):
          system_packages.update(self._iter_dir_packages(path))
        else:
          system_packages.update(self._iter_jar_packages(path))
    return system_packages

  @property
  def system_packages(self):
    if self._system_packages is None:
      self._system_packages = self._calculate_system_packages()
    return self._system_packages

  def assemble_binary_rules(self, main, jar, custom_rules=None):
    """Creates an ordered list of rules suitable for fully shading the given binary.

    The default rules will ensure the `main` class name is un-changed along with a minimal set of
    support classes but that everything else will be shaded.

    Any `custom_rules` are given highest precedence and so they can interfere with this automatic
    binary shading.  In general it's safe to add exclusion rules to open up classes that need to be
    shared between the binary and the code it runs over.  An example would be excluding the
    `org.junit.Test` annotation class from shading since a tool running junit needs to be able
    to scan for this annotation inside the user code it tests.

    :param unicode main: The main class to preserve as the entry point.
    :param unicode jar: The path of the binary jar the `main` class lives in.
    :param list custom_rules: An optional list of custom `Shader.Rule`s.
    :returns: a precedence-ordered list of `Shader.Rule`s
    """
    # If a class is matched by multiple rules, the 1st lexical match wins (see:
    # https://code.google.com/p/jarjar/wiki/CommandLineDocs#Rules_file_format).
    # As such we 1st ensure the `main` package and the jre packages have exclusion rules and
    # then apply a final set of shading rules to everything else at lowest precedence.

    # Custom rules take precedence.
    rules = list(custom_rules or [])

    # Exclude the main entrypoint's package from shading. There may be package-private classes that
    # the main class accesses so we must preserve the whole package).
    parts = main.rsplit('.', 1)
    if len(parts) == 2:
      main_package = parts[0]
    else:
      # There is no package component, so the main class is in the root (default) package.
      main_package = None
    rules.append(self.exclude_package(main_package))

    rules.extend(self.exclude_package(system_pkg) for system_pkg in sorted(self.system_packages))

    # Shade everything else.
    #
    # NB: A simpler way to do this jumps out - just emit 1 wildcard rule:
    #
    #   rule **.* _shaded_.@1.@2
    #
    # Unfortunately, as of jarjar 1.4 this wildcard catch-all technique improperly transforms
    # resources in the `main_package`.  The jarjar binary jar itself has its command line help text
    # stored as a resource in its main's package and so using a catch-all like this causes
    # recursively shading jarjar with itself using this class to fail!
    #
    # As a result we explicitly shade all the non `main_package` packages in the binary jar instead
    # which does support recursively shading jarjar.
    rules.extend(self.shade_package(pkg) for pkg in sorted(self._iter_jar_packages(jar))
                 if pkg != main_package)

    return rules

  @contextmanager
  def temporary_rules_file(self, rules):
    with temporary_file() as fp:
      for rule in rules:
        fp.write(rule.render())
      fp.close()
      yield fp.name

  @contextmanager
  def binary_shader_for_rules(self, output_jar, jar, rules, jvm_options=None):
    """Yields an `Executor.Runner` that will perform shading of the binary `jar` when `run()`.

    No default rules are applied; only the rules passed in as a parameter will be used.

    :param unicode output_jar: The path to dump the shaded jar to; will be over-written if it
                               exists.
    :param unicode jar: The path to the jar file to shade.
    :param list rules: The rules to apply for shading.
    :param list jvm_options: an optional sequence of options for the underlying jvm
    :returns: An `Executor.Runner` that can be `run()` to shade the given `jar`.
    :rtype: :class:`pants.java.executor.Executor.Runner`
    """
    with self.temporary_rules_file(rules) as rules_file:
      yield self._executor.runner(classpath=self._jarjar_classpath,
                                  main='org.pantsbuild.jarjar.Main',
                                  jvm_options=jvm_options,
                                  args=['process', rules_file, jar, output_jar])

  def binary_shader(self, output_jar, main, jar, custom_rules=None, jvm_options=None):
    """Yields an `Executor.Runner` that will perform shading of the binary `jar` when `run()`.

    The default rules will ensure the `main` class name is un-changed along with a minimal set of
    support classes but that everything else will be shaded.

    Any `custom_rules` are given highest precedence and so they can interfere with this automatic
    binary shading.  In general its safe to add exclusion rules to open up classes that need to be
    shared between the binary and the code it runs over.  An example would be excluding the
    `org.junit.Test` annotation class from shading since both a tool running junit needs to be able
    to scan for this annotation applied to the user code it tests.

    :param unicode output_jar: The path to dump the shaded jar to; will be over-written if it
                               exists.
    :param unicode main: The main class in the `jar` to preserve as the entry point.
    :param unicode jar: The path to the jar file to shade.
    :param list custom_rules: An optional list of custom `Shader.Rule`s.
    :param list jvm_options: an optional sequence of options for the underlying jvm
    :returns: An `Executor.Runner` that can be `run()` to shade the given `jar`.
    :rtype: :class:`pants.java.executor.Executor.Runner`
    """
    all_rules = self.assemble_binary_rules(main, jar, custom_rules=custom_rules)
    return self.binary_shader_for_rules(output_jar, jar, all_rules, jvm_options=jvm_options)
