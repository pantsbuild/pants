# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.address_lookup_error import AddressLookupError
from pants.base.exceptions import TaskError
from pants.option.options import Options


class JvmToolMixin(object):
  """A mixin for registering and accessing JVM-based tools.

  Must be mixed in to something that can register and use options, e.g., a Task or a Subsystem.
  """
  class DepLookupError(AddressLookupError):
    """Thrown when a dependency can't be found."""
    pass

  _tool_keys = []  # List of (scope, key, main, custom_rule) tuples.

  @classmethod
  def register_jvm_tool(cls, register, key, default=None, main=None, custom_rules=None):
    """Registers a jvm tool under `key` for lazy classpath resolution.

    Classpaths can be retrieved in `execute` scope via `tool_classpath`.

    NB: If the tool's `main` class name is supplied the tool classpath will be shaded.

    :param register: A function that can register options with the option system.
    :param unicode key: The key the tool configuration should be registered under.
    :param list default: The default tool classpath target address specs to use.
    :param unicode main: The fully qualified class name of the tool's main class if shading of the
                         tool classpath is desired.
    :param list custom_rules: An optional list of `Shader.Rule`s to apply before the automatically
                              generated binary jar shading rules.  This is useful for excluding
                              classes shared between the tool and the code it runs over.  The
                              canonical example is the `org.junit.Test` annotation read by junit
                              runner tools from user code. In this sort of case the shared code must
                              have a uniform name between the tool and the user code and so the
                              shared code must be excluded from shading.
    """
    register('--{0}'.format(key),
             advanced=True,
             type=Options.list,
             default=default or ['//:{0}'.format(key)],
             help='Target specs for bootstrapping the {0} tool.'.format(key))

    # TODO(John Sirois): Move towards requiring tool specs point to jvm_binary targets.
    # These already have a main and are a natural place to house any custom shading rules.  That
    # would eliminate the need to pass main and custom_rules here.
    # It is awkward that jars can no longer be inlined as dependencies - this will require 2 targets
    # for every tool - the jvm_binary, and a jar_library for its dependencies to point to.  It may
    # be worth creating a JarLibrary subclass - say JarBinary, or else mixing in a Binary interface
    # to JarLibrary to endow it with main and shade_rules attributes to allow for single-target
    # definition of resolvable jvm binaries.
    JvmToolMixin._tool_keys.append((register.scope, key, main, custom_rules))

  @staticmethod
  def get_registered_tools():
    return JvmToolMixin._tool_keys

  @staticmethod
  def reset_registered_tools():
    """Needed only for test isolation."""
    JvmToolMixin._tool_keys = []

  def tool_targets(self, context, key):
    """Return the Target objects obtained by resolving a tool's specs."""
    specs = self.get_options()[key]
    targets = []
    for spec in specs:
      # Resolve to actual targets.
      try:
        targets.extend(context.resolve(spec))
      except AddressLookupError as e:
        raise self.DepLookupError("{message}\n  specified by option --{key} in scope {scope}."
                                  .format(message=e,
                                          key=key,
                                          scope=self.options_scope))
    return targets

  def tool_classpath_from_products(self, products, key, scope):
    """Get a classpath for the tool previously registered under key in the given scope.

    Returns a list of paths.
    """
    callback_product_map = products.get_data('jvm_build_tools_classpath_callbacks') or {}
    callback = callback_product_map.get(scope, {}).get(key)
    if not callback:
      raise TaskError('No bootstrap callback registered for {key} in {scope}'
                      .format(key=key, scope=scope))
    return callback()
