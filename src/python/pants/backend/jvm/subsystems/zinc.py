# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.subsystems.shader import Shader
from pants.java.jar.jar_dependency import JarDependency
from pants.subsystem.subsystem import Subsystem


class Zinc(Subsystem, JvmToolMixin):
  """Configuration for Pants' zinc wrapper tool."""

  options_scope = 'zinc'

  ZINC_COMPILE_MAIN = 'org.pantsbuild.zinc.Main'

  @classmethod
  def register_options(cls, register):
    super(Zinc, cls).register_options(register)
    Zinc.register_options_for(cls, register)

  @staticmethod
  def register_options_for(jvm_tool_mixin_cls, register, **kwargs):
    """Register options for the zinc tool in the context of the given JvmToolMixin.
    
    TODO: Move into the classmethod after zinc registration has been removed
    from `zinc_compile` in `1.6.0.dev0`.
    """
    cls = jvm_tool_mixin_cls

    def sbt_jar(name, **kwargs):
      return JarDependency(org='org.scala-sbt', name=name, rev='1.0.0-X5', **kwargs)

    shader_rules = [
        # The compiler-interface and compiler-bridge tool jars carry xsbt and
        # xsbti interfaces that are used across the shaded tool jar boundary so
        # we preserve these root packages wholesale along with the core scala
        # APIs.
        Shader.exclude_package('scala', recursive=True),
        Shader.exclude_package('xsbt', recursive=True),
        Shader.exclude_package('xsbti', recursive=True),
      ]

    cls.register_jvm_tool(register,
                          'zinc',
                          classpath=[
                            JarDependency('org.pantsbuild', 'zinc_2.10', '0.0.5'),
                          ],
                          main=Zinc.ZINC_COMPILE_MAIN,
                          custom_rules=shader_rules,
                          **kwargs)

    cls.register_jvm_tool(register,
                          'compiler-bridge',
                          classpath=[
                            sbt_jar(name='compiler-bridge_2.10',
                                    classifier='sources',
                                    intransitive=True)
                          ],
                          **kwargs)
    cls.register_jvm_tool(register,
                          'compiler-interface',
                          classpath=[
                            sbt_jar(name='compiler-interface')
                          ],
                          # NB: We force a noop-jarjar'ing of the interface, since it is now broken
                          # up into multiple jars, but zinc does not yet support a sequence of jars
                          # for the interface.
                          main='no.such.main.Main',
                          custom_rules=shader_rules,
                          **kwargs)
