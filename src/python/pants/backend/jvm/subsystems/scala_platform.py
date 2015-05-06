# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.option.options import Options
from pants.subsystem.subsystem import Subsystem


class ScalaPlatform(JvmToolMixin, Subsystem):
  """A scala platform.

  TODO: Rework so there's a way to specify a default as direct pointers to jar coordinates,
  so we don't require specs in BUILD.tools if the default is acceptable.
  """

  @classmethod
  def scope_qualifier(cls):
    return 'scala-platform'

  @classmethod
  def register_options(cls, register):
    super(ScalaPlatform, cls).register_options(register)
    register('--runtime', advanced=True, type=Options.list, default=['//:scala-library'],
             help='Target specs pointing to the scala runtime libraries.')
    cls.register_jvm_tool(register, 'scalac', default=['//:scala-compiler'])

  def compiler_classpath(self, products):
    return self.tool_classpath_from_products(products, 'scalac', scope=self.options_scope)

  @property
  def runtime(self):
    return self.get_options().runtime
