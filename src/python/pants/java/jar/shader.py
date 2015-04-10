# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import namedtuple
from contextlib import contextmanager

from pants.java.executor import SubprocessExecutor
from pants.util.contextutil import open_zip, temporary_file


# TODO(John Sirois): Support shading given an input jar and a set of user-supplied rules (these
# will come from target attributes) instead of only supporting auto-generating rules from the main
# class of the input jar.
class Shader(object):
  """Creates shaded jars."""

  class Error(Exception):
    """Indicates an error shading a jar."""

  class Rule(namedtuple('Rule', ['from_pattern', 'to_pattern'])):
    """Represents a transformation rule for a jar shading session."""

    def render(self):
      return 'rule {0} {1}\n'.format(self.from_pattern, self.to_pattern)

  SHADE_PREFIX = '__shaded_by_pants__.'
  """The shading package."""

  @classmethod
  def _package_rule(cls, package_name=None, recursive=False, shade=False):
    args = dict(package=package_name,
                capture='**' if recursive else '*',
                dest_prefix=cls.SHADE_PREFIX if shade else '')

    if package_name:
      return cls.Rule(from_pattern='{package}.{capture}'.format(**args),
                      to_pattern='{dest_prefix}{package}.@1'.format(**args))
    else:
      return cls.Rule(from_pattern='{capture}'.format(**args),
                      to_pattern='{dest_prefix}@1'.format(**args))

  @classmethod
  def _class_rule(cls, class_name, shade=False):
    args = dict(class_name=class_name,
                dest_prefix=cls.SHADE_PREFIX if shade else '')

    return cls.Rule(from_pattern=class_name, to_pattern='{dest_prefix}{class_name}'.format(**args))

  @classmethod
  def exclude_package(cls, package_name=None, recursive=False):
    """Excludes the given fully qualified package name from shading.

    :param unicode package_name: A fully qualified package_name; eg: `org.pantsbuild`; `None` for
                                the java default (root) package.
    :param bool recursive: `True` to exclude any package with `package_name` as a proper prefix;
                           `False` by default.
    :returns: A `Shader.Rule` describing the shading exclusion.
    """
    return cls._package_rule(package_name, recursive, shade=False)

  @classmethod
  def exclude_class(cls, class_name):
    """Excludes the given fully qualified class name from shading.

    :param unicode class_name: A fully qualified classname, eg: `org.pantsbuild.tools.jar.Main`.
    :returns: A `Shader.Rule` describing the shading exclusion.
    """
    return cls._class_rule(class_name, shade=False)

  @classmethod
  def shade_package(cls, package_name=None, recursive=False):
    """Includes the given fully qualified package name in shading.

    :param unicode package_name: A fully qualified package_name; eg: `org.pantsbuild`; `None` for
                                 the java default (root) package.
    :param bool recursive: `True` to include any package with `package_name` as a proper prefix;
                           `False` by default.
    :returns: A `Shader.Rule` describing the packages to be shaded.
    """
    return cls._package_rule(package_name, recursive, shade=True)

  @classmethod
  def shade_class(cls, class_name):
    """Includes the given fully qualified class in shading.

    :param unicode class_name: A fully qualified classname, eg: `org.pantsbuild.tools.jar.Main`.
    :returns: A `Shader.Rule` describing the class shading.
    """
    return cls._class_rule(class_name, shade=True)

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
    with open_zip(path) as jar:
      paths = set()
      for pathname in jar.namelist():
        if cls._potential_package_path(pathname):
          paths.add(os.path.dirname(pathname))
      return cls._iter_packages(paths)

  def __init__(self, jarjar, executor=None):
    """Creates a `Shader` the will use the given `jarjar` jar to create shaded jars.

    :param unicode jarjar: The path to the jarjar jar.
    :param executor: An optional java `Executor` to use to create shaded jar files.  Defaults to a
                    `SubprocessExecutor` that uses the default java distribution.
    """
    self._jarjar = jarjar
    self._executor = executor or SubprocessExecutor()
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
  def binary_shader(self, output_jar, main, jar, custom_rules=None):
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
    :returns: An `Executor.Runner` that can be `run()` to shade the given `jar`.
    """
    with temporary_file() as fp:
      for rule in self.assemble_binary_rules(main, jar, custom_rules=custom_rules):
        fp.write(rule.render())
      fp.close()

      yield self._executor.runner(classpath=[self._jarjar],
                                  main='com.tonicsystems.jarjar.Main',
                                  args=['process', fp.name, jar, output_jar])
