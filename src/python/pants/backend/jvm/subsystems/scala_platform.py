# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.subsystems.jvm_tool_mixin import JvmToolMixin
from pants.option.custom_types import list_option
from pants.subsystem.subsystem import Subsystem


class ScalaPlatform(JvmToolMixin, Subsystem):
  """A scala platform.

  TODO: Rework so there's a way to specify a default as direct pointers to jar coordinates,
  so we don't require specs in BUILD.tools if the default is acceptable.
  """
  options_scope = 'scala-platform'

  @classmethod
  def register_options(cls, register):
    super(ScalaPlatform, cls).register_options(register)
    # No need to fingerprint --runtime, because it is automatically inserted as a
    # dependency for the scala_library target.
    register('--runtime', advanced=True, type=list_option, default=['//:scala-library'],
             help='Target specs pointing to the scala runtime libraries.')
    cls.register_jvm_tool(register, 'scalac', default=['//:scala-compiler'], fingerprint=True)

  def compiler_classpath(self, products):
    return self.tool_classpath_from_products(products, 'scalac', scope=self.options_scope)

  @property
  def runtime(self):
    return self.get_options().runtime
