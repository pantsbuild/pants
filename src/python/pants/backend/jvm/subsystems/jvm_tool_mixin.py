# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from collections import namedtuple
from textwrap import dedent

from pants.base.dep_lookup_error import DepLookupError
from pants.base.exceptions import TaskError


class JvmToolMixin(object):
  """A mixin for registering and accessing JVM-based tools.

  Must be mixed in to something that can register and use options, e.g., a Task or a Subsystem.
  """
  class InvalidToolClasspath(TaskError):
    """Indicates an invalid jvm tool classpath."""

  class JvmTool(namedtuple('JvmTool', ['scope', 'key', 'classpath', 'main', 'custom_rules'])):
    """Represents a jvm tool classpath request."""

    def dep_spec(self, options):
      """Returns the target address spec that points to this JVM tool's classpath dependencies.

      :rtype: string
      """
      option = self.key.replace('-', '_')
      dep_spec = options.for_scope(self.scope)[option]
      if dep_spec.startswith('['):
        raise ValueError(dedent("""\
          JVM tool configuration now expects a single target address, use the
          following in pants.ini:

          [{scope}]
          {key}: //tool/classpath:address
          """.format(scope=self.scope, key=self.key)))
      return dep_spec

    def is_default(self, options):
      """Return `True` if this option was not set by the user.

      :rtype: bool
      """
      return options.for_scope(self.scope).is_default(self.key.replace('-', '_'))

  _jvm_tools = []  # List of JvmTool objects.

  @classmethod
  def register_jvm_tool(cls,
                        register,
                        key,
                        classpath_spec=None,
                        main=None,
                        custom_rules=None,
                        fingerprint=True,
                        classpath=None,
                        help=None):
    """Registers a jvm tool under `key` for lazy classpath resolution.

    Classpaths can be retrieved in `execute` scope via `tool_classpath`.

    NB: If the tool's `main` class name is supplied the tool classpath will be shaded.

    :param register: A function that can register options with the option system.
    :param unicode key: The key the tool configuration should be registered under.
    :param unicode classpath_spec: The tool classpath target address spec that can be used to
                                   override this tool's classpath; by default, `//:[key]`.
    :param unicode main: The fully qualified class name of the tool's main class if shading of the
                         tool classpath is desired.
    :param list custom_rules: An optional list of `Shader.Rule`s to apply before the automatically
                              generated binary jar shading rules.  This is useful for excluding
                              classes shared between the tool and the code it runs over.  The
                              canonical example is the `org.junit.Test` annotation read by junit
                              runner tools from user code. In this sort of case the shared code must
                              have a uniform name between the tool and the user code and so the
                              shared code must be excluded from shading.
    :param bool fingerprint: Indicates whether to include the jvm tool in the task's fingerprint.
                             Note that unlike for other options, fingerprinting is enabled for tools
                             by default.
    :param list classpath: A list of one or more `JarDependency` objects that form this tool's
                           default classpath.  If the classpath is optional, supply an empty list;
                           otherwise the default classpath of `None` indicates the `classpath_spec`
                           must point to a target defined in a BUILD file that provides the tool
                           classpath.
    :param unicode help: An optional custom help string; otherwise a reasonable one is generated.
    """
    def formulate_help():
      if classpath:
        return ('Target address spec for overriding the classpath of the {} jvm tool which is, '
                'by default: {}'.format(key, classpath))
      else:
        return 'Target address spec for specifying the classpath of the {} jvm tool.'.format(key)
    help = help or formulate_help()

    register('--{}'.format(key),
             advanced=True,
             default='//:{}'.format(key) if classpath_spec is None else classpath_spec,
             help=help,
             fingerprint=fingerprint)

    # TODO(John Sirois): Move towards requiring tool specs point to jvm_binary targets.
    # These already have a main and are a natural place to house any custom shading rules.  That
    # would eliminate the need to pass main and custom_rules here.
    # It is awkward that jars can no longer be inlined as dependencies - this will require 2 targets
    # for every tool - the jvm_binary, and a jar_library for its dependencies to point to.  It may
    # be worth creating a JarLibrary subclass - say JarBinary, or else mixing in a Binary interface
    # to JarLibrary to endow it with main and shade_rules attributes to allow for single-target
    # definition of resolvable jvm binaries.
    jvm_tool = cls.JvmTool(register.scope, key, classpath, main, custom_rules)
    JvmToolMixin._jvm_tools.append(jvm_tool)

  @classmethod
  def prepare_tools(cls, round_manager):
    """Subclasses must call this method to ensure jvm tool products are available."""
    round_manager.require_data('jvm_build_tools_classpath_callbacks')

  @staticmethod
  def get_registered_tools():
    """Returns all registered jvm tools.

    :rtype: list of :class:`JvmToolMixin.JvmTool`
    """
    return JvmToolMixin._jvm_tools

  @staticmethod
  def reset_registered_tools():
    """Needed only for test isolation."""
    JvmToolMixin._jvm_tools = []

  def tool_jar_from_products(self, products, key, scope):
    """Get the jar for the tool previously registered under key in the given scope.

    :param products: The products of the current pants run.
    :type products: :class:`pants.goal.products.Products`
    :param string key: The key the tool configuration was registered under.
    :param string scope: The scope the tool configuration was registered under.
    :returns: A single jar path.
    :rtype: string
    :raises: `JvmToolMixin.InvalidToolClasspath` when the tool classpath is not composed of exactly
             one jar.
    """
    classpath = self.tool_classpath_from_products(products, key, scope)
    if len(classpath) != 1:
      params = dict(tool=key, scope=scope, count=len(classpath), classpath='\n\t'.join(classpath))
      raise self.InvalidToolClasspath('Expected tool {tool} in scope {scope} to resolve to one '
                                      'jar, instead found {count}:\n\t{classpath}'.format(**params))
    return classpath[0]

  def tool_classpath_from_products(self, products, key, scope):
    """Get a classpath for the tool previously registered under key in the given scope.

    :param products: The products of the current pants run.
    :type products: :class:`pants.goal.products.Products`
    :param string key: The key the tool configuration was registered under.
    :param string scope: The scope the tool configuration was registered under.
    :returns: A list of paths.
    :rtype: list
    """
    callback_product_map = products.get_data('jvm_build_tools_classpath_callbacks') or {}
    callback = callback_product_map.get(scope, {}).get(key)
    if not callback:
      raise TaskError('No bootstrap callback registered for {key} in {scope}'
                      .format(key=key, scope=scope))
    return callback()
