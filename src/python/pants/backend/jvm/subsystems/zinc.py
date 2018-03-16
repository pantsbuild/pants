# coding=utf-8
# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.backend.jvm.subsystems.shader import Shader
from pants.java.jar.jar_dependency import JarDependency
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


class Zinc(object):
  """Configuration for Pants' zinc wrapper tool."""

  ZINC_COMPILE_MAIN = 'org.pantsbuild.zinc.Main'

  class Factory(Subsystem, JvmToolMixin):
    options_scope = 'zinc'

    @classmethod
    def register_options(cls, register):
      super(Zinc.Factory, cls).register_options(register)

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
                            custom_rules=shader_rules)

      cls.register_jvm_tool(register,
                            'compiler-bridge',
                            classpath=[
                              sbt_jar(name='compiler-bridge_2.10',
                                      classifier='sources',
                                      intransitive=True)
                            ])
      cls.register_jvm_tool(register,
                            'compiler-interface',
                            classpath=[
                              sbt_jar(name='compiler-interface')
                            ],
                            # NB: We force a noop-jarjar'ing of the interface, since it is now
                            # broken up into multiple jars, but zinc does not yet support a sequence
                            # of jars for the interface.
                            main='no.such.main.Main',
                            custom_rules=shader_rules)

    @classmethod
    def _zinc(cls, products):
      return cls.tool_classpath_from_products(products, 'zinc', cls.options_scope)

    @classmethod
    def _compiler_bridge(cls, products):
      return cls.tool_jar_from_products(products, 'compiler-bridge', cls.options_scope)

    @classmethod
    def _compiler_interface(cls, products):
      return cls.tool_jar_from_products(products, 'compiler-interface', cls.options_scope)

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
