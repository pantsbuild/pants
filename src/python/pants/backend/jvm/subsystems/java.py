# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.subsystems.zinc_language_mixin import ZincLanguageMixin
from pants.build_graph.address import Address
from pants.option.custom_types import target_option
from pants.subsystem.subsystem import Subsystem


class Java(JvmToolMixin, ZincLanguageMixin, Subsystem):
  """A subsystem to encapsulate compile-time settings and features for the Java language.

  Runtime options are captured by the JvmPlatform subsystem.
  """
  options_scope = 'java'

  @classmethod
  def register_options(cls, register):
    super(Java, cls).register_options(register)
    # This target, if specified, serves as both a tool (for compiling java code) and a
    # dependency (for javac plugins).  See below for the different methods for accessing
    # classpath entries (in the former case) or target specs (in the latter case).
    #
    # Javac plugins can access basically all of the compiler internals, so we don't shade anything.
    # Hence the unspecified main= argument. This tool is optional, hence the empty classpath list.
    cls.register_jvm_tool(register,
                          'javac',
                          classpath=[],
                          help='Java compiler to use.  If unspecified, we use the compiler '
                               'embedded in the Java distribution we run on.')

    register('--compiler-plugin-deps', advanced=True, type=list, member_type=target_option,
             fingerprint=True,
             help='Requested javac plugins will be found in these targets, as well as in any '
                  'dependencies of the targets being compiled.')

  @classmethod
  def global_javac_spec(cls, buildgraph):
    """Returns a target spec for the java compiler library, useable as a dependency.

    If no javac library is specified, will return None.  The caller must handle
    this case by defaulting to the JDK's tools.jar.  We can't provide a spec for that
    jar here because it would create a circular dependency between this subsystem and JVM targets.

    :param pants.build_graph.build_graph.BuildGraph buildgraph: buildgraph object.
    :return: a target spec or None
    """
    javac_spec = cls.global_instance().javac_spec()
    if buildgraph.contains_address(Address.parse(javac_spec)):
      return javac_spec
    return None

  @classmethod
  def global_plugin_dependency_specs(cls):
    # TODO: This check is a hack to allow tests to pass without having to set up subsystems.
    # We have hundreds of tests that use JvmTargets, either as a core part of the test, or
    # incidentally when testing build graph functionality, and it would be onerous to make them
    # all set up a subsystem they don't care about.
    # See https://github.com/pantsbuild/pants/issues/3409.
    if cls.is_initialized():
      return cls.global_instance().plugin_dependency_specs()
    else:
      return []

  @classmethod
  def global_javac_classpath(cls, products):
    """Returns a classpath entry for the java compiler library, useable as a tool.

    If no javac library is specified, will return an empty list.  The caller must handle
    this case by defaulting to the JDK's tools.jar.  We can't provide that jar here
    because we'd have to know about a Distribution.
    """
    return cls.global_instance().javac_classpath(products)

  def __init__(self, *args, **kwargs):
    super(Java, self).__init__(*args, **kwargs)
    opts = self.get_options()

    # TODO: These checks are a continuation of the hack that allows tests to pass without caring
    # about this subsystem.
    if hasattr(opts, 'javac') and opts.javac:
      self._javac_spec = opts.javac
    else:
      self._javac_spec = None
    if hasattr(opts, 'compiler_plugin_deps'):
      # Parse the specs in order to normalize them, so we can do string comparisons on them in
      # JvmTarget in order to avoid creating self-referencing deps.
      self._dependency_specs = [Address.parse(spec).spec for spec in opts.compiler_plugin_deps]
    else:
      self._dependency_specs = []

  def plugin_dependency_specs(self):
    return self._dependency_specs

  def javac_spec(self):
    return self._javac_spec

  def javac_classpath(self, products):
    return self.tool_classpath_from_products(products, 'javac', self.options_scope)
