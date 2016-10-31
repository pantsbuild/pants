# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.subsystems.shader import Shader
from pants.backend.jvm.targets.jar_dependency import JarDependency
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.build_graph.address import Address
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_method


class JUnit(JvmToolMixin, Subsystem):
  options_scope = 'junit'

  LIBRARY_REV = '4.12'
  RUNNER_MAIN = 'org.pantsbuild.tools.junit.ConsoleRunner'

  _LIBRARY_JAR = JarDependency(org='junit', name='junit', rev=LIBRARY_REV)
  _RUNNER_JAR = JarDependency(org='org.pantsbuild', name='junit-runner', rev='1.0.16')

  @classmethod
  def register_options(cls, register):
    super(JUnit, cls).register_options(register)
    cls.register_jvm_tool(register,
                          'junit_library',
                          classpath=[
                            cls._LIBRARY_JAR,
                          ])

    cls.register_jvm_tool(register,
                          'junit',
                          classpath=[
                            cls._RUNNER_JAR,
                          ],
                          main=cls.RUNNER_MAIN,
                          # TODO(John Sirois): Investigate how much less we can get away with.
                          # Clearly both tests and the runner need access to the same @Test,
                          # @Before, as well as other annotations, but there is also the Assert
                          # class and some subset of the @Rules, @Theories and @RunWith APIs.
                          custom_rules=[
                            Shader.exclude_package('junit.framework', recursive=True),
                            Shader.exclude_package('org.junit', recursive=True),
                            Shader.exclude_package('org.hamcrest', recursive=True),
                            Shader.exclude_package('org.pantsbuild.junit.annotations',
                                                   recursive=True),
                          ])

  @memoized_method
  def library_spec(self, buildgraph):
    """Returns a target spec for the junit library, useable as a dependency.

    :param pants.build_graph.build_graph.BuildGraph buildgraph: buildgraph object.
    :return: a target spec
    """
    junit_addr = Address.parse(self.get_options().junit_library)
    if not buildgraph.contains_address(junit_addr):
      buildgraph.inject_synthetic_target(junit_addr, JarLibrary, jars=[self._LIBRARY_JAR],
                                         scope='forced')
    return junit_addr.spec

  def runner_classpath(self, context):
    """Returns an iterable of classpath elements for the runner.
    """
    return self.tool_classpath_from_products(context.products, 'junit', self.options_scope)
