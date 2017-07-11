# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.subsystems.zinc_language_mixin import ZincLanguageMixin
from pants.backend.jvm.targets.tools_jar import ToolsJar
from pants.build_graph.address import Address
from pants.option.custom_types import target_option
from pants.subsystem.subsystem import Subsystem


# TODO: Sort out JVM compile config model: https://github.com/pantsbuild/pants/issues/4483.
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
             removal_version='1.5.0.dev0',
             removal_hint='See http://www.pantsbuild.org/javac_plugins.html#depending-on-plugins.',
             fingerprint=True)

  def injectables(self, build_graph):
    # N.B. This method would normally utilize `injectables_spec_for_key(key)` to get at
    # static specs, but due to the need to check the buildgraph before determining whether
    # the javac spec is valid we must handle the injectables here without poking the
    # `injectables_spec_mapping` property.
    javac_spec = self._javac_spec
    if not javac_spec:
      self._javac_exists = False
    else:
      javac_address = Address.parse(javac_spec)
      self._javac_exists = True if build_graph.contains_address(javac_address) else False

    toolsjar_spec = self._tools_jar_spec
    if toolsjar_spec:
      synthetic_address = Address.parse(toolsjar_spec)
      if not build_graph.contains_address(synthetic_address):
        build_graph.inject_synthetic_target(synthetic_address, ToolsJar)

  @property
  def javac_specs(self):
    if not self._javac_spec:
      return []
    assert self._javac_exists is not None, (
      'cannot access javac_specs until injectables is called'
    )
    return [self._javac_spec] if self._javac_exists else []

  @property
  def injectables_spec_mapping(self):
    return {
      'plugin': self._plugin_dependency_specs,
      # If no javac library is specified, this maps to None. The caller must handle
      # this case by defaulting to the JDK's tools.jar.
      'javac': self.javac_specs,
      'tools.jar': [self._tools_jar_spec]
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
    self._javac_spec = getattr(opts, 'javac', None)
    self._javac_exists = None
    self._plugin_dependency_specs = [
      Address.parse(spec).spec for spec in getattr(opts, 'compiler_plugin_deps', [])
    ]
    self._tools_jar_spec = '//:tools-jar-synthetic'

  def javac_classpath(self, products):
    return self.tool_classpath_from_products(products, 'javac', self.options_scope)
