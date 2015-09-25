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
    # TODO: The choice of a platform version should likely drive automatic selection of the
    # appropriate scala-library and scala-compiler dependencies.
    register('--version', advanced=True, default='2.10',
             help='The scala "platform version", which is suffixed onto all published '
                  'libraries. This should match the declared compiler/library versions.')
    cls.register_jvm_tool(register, 'scalac', classpath_spec='//:scala-compiler')

  def compiler_classpath(self, products):
    return self.tool_classpath_from_products(products, 'scalac', scope=self.options_scope)

  @property
  def version(self):
    return self.get_options().version

  def suffix_version(self, name):
    """Appends the platform version to the given artifact name.

    Also validates that the name doesn't already end with the version.
    """
    if name.endswith(self.version):
      raise ValueError('The name "{0}" should not be suffixed with the scala platform version '
                      '({1}): it will be added automatically.'.format(name, self.version))
    return '{0}_{1}'.format(name, self.version)

  @property
  def runtime(self):
    return self.get_options().runtime
