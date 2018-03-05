# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.subsystems.zinc_language_mixin import ZincLanguageMixin
from pants.backend.jvm.targets.tools_jar import ToolsJar
from pants.build_graph.address import Address
from pants.build_graph.injectables_mixin import InjectablesMixin
from pants.subsystem.subsystem import Subsystem


# TODO: Sort out JVM compile config model: https://github.com/pantsbuild/pants/issues/4483.
class Java(JvmToolMixin, ZincLanguageMixin, InjectablesMixin, Subsystem):
  """A subsystem to encapsulate compile-time settings and features for the Java language.

  Runtime options are captured by the JvmPlatform subsystem.
  """
  options_scope = 'java'

  _javac_tool_name = 'javac'
  _default_javac_spec = '//:{}'.format(_javac_tool_name)

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
                          cls._javac_tool_name,
                          classpath=[],
                          help='Java compiler to use.  If unspecified, we use the compiler '
                               'embedded in the Java distribution we run on.')

  def injectables(self, build_graph):
    tools_jar_address = Address.parse(self._tools_jar_spec)
    if not build_graph.contains_address(tools_jar_address):
      build_graph.inject_synthetic_target(tools_jar_address, ToolsJar)
    elif not build_graph.get_target(tools_jar_address).is_synthetic:
      raise build_graph.ManualSyntheticTargetError(tools_jar_address)

  @property
  def injectables_spec_mapping(self):
    return {
      # Zinc directly accesses the javac tool.
      'javac': [self._javac_spec],
      # The ProvideToolsJar task will first attempt to use the (optional) configured
      # javac tool, and then fall back to injecting a classpath entry linking to the current
      # distribution's `tools.jar`.
      'tools.jar': [self._tools_jar_spec],
    }

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
    # TODO: These checks are a continuation of the hack that allows tests to pass without
    # caring about this subsystem.
    self._javac_spec = getattr(opts, 'javac', self._default_javac_spec)
    self._tools_jar_spec = '//:tools-jar-synthetic'

  def javac_classpath(self, products):
    return self.tool_classpath_from_products(products, 'javac', self.options_scope)
