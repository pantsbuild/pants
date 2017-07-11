# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.subsystem.subsystem import Subsystem


class ThriftDefaults(Subsystem):
  """Tracks defaults for java thrift target attributes that influence code generation."""
  options_scope = 'thrift-defaults'

  # TODO: These exist to support alternate compilers (specifically scrooge), but this should
  # probably be a scrooge-specific subsystem, tied to a scrooge_thrift_library target type.
  # These options (e.g., rpc_style, language) are relevant to scrooge but may have no meaning
  # in some other compiler (they certainly don't in the apache thrift compiler).
  @classmethod
  def register_options(cls, register):
    register('--compiler', type=str, advanced=True, default='thrift',
             help='The default compiler to use for java_thrift_library targets.')
    register('--language', type=str, advanced=True, default='java',
             help='The default language to generate for java_thrift_library targets.')
    register('--rpc-style', type=str, advanced=True, default='sync',
             removal_version='1.6.0.dev0',
             removal_hint='Use --compiler-args instead of --rpc-style.',
             help='The default rpc-style to generate for java_thrift_library targets.')
    register('--default-java-namespace', type=str, advanced=True, default=None,
             help='The default Java namespace to generate for java_thrift_library targets.')
    register('--namespace-map', type=dict, advanced=True, default={},
             help='The default namespace map to generate for java_thrift_library targets, {old: new}.')
    register('--compiler-args', type=list, advanced=True, default=[],
             help='Extra arguments for the thrift compiler.')

  def __init__(self, *args, **kwargs):
    super(ThriftDefaults, self).__init__(*args, **kwargs)
    self._default_compiler = self.get_options().compiler
    self._default_language = self.get_options().language
    self._default_rpc_style = self.get_options().rpc_style
    self._default_default_java_namespace = self.get_options().default_java_namespace
    self._default_namespace_map = self.get_options().namespace_map
    self._default_compiler_args = self.get_options().compiler_args

  def compiler(self, target):
    """Returns the thrift compiler to use for the given target.

    :param target: The target to extract the thrift compiler from.
    :type target: :class:`pants.backend.codegen.thrift.java.java_thrift_library.JavaThriftLibrary`
    :returns: The thrift compiler to use.
    :rtype: string
    """
    self._check_target(target)
    return target.compiler or self._default_compiler

  def language(self, target):
    """Returns the target language to generate thrift stubs for.

    :param target: The target to extract the target language from.
    :type target: :class:`pants.backend.codegen.thrift.java.java_thrift_library.JavaThriftLibrary`
    :returns: The target language to generate stubs for.
    :rtype: string
    """
    self._check_target(target)
    return target.language or self._default_language

  def namespace_map(self, target):
    """Returns the namespace_map used for Thrift generation.

    :param target: The target to extract the namespace_map from.
    :type target: :class:`pants.backend.codegen.targets.java_thrift_library.JavaThriftLibrary`
    :returns: The namespaces to remap (old to new).
    :rtype: dictionary
    """
    self._check_target(target)
    return target.namespace_map or self._default_namespace_map

  def compiler_args(self, target):
    """Returns the compiler_args used for Thrift generation.

    :param target: The target to extract the compiler args from.
    :type target: :class:`pants.backend.codegen.targets.java_thrift_library.JavaThriftLibrary`
    :returns: Extra arguments for the thrift compiler
    :rtype: list
    """
    self._check_target(target)
    return target.compiler_args or self._default_compiler_args

  def default_java_namespace(self, target):
    """Returns the default_java_namespace used for Thrift generation.

    :param target: The target to extract the default_java_namespace from.
    :type target: :class:`pants.backend.codegen.targets.java_thrift_library.JavaThriftLibrary`
    :returns: The default Java namespace used when not specified in the IDL.
    :rtype: string
    """
    self._check_target(target)
    return target.default_java_namespace or self._default_default_java_namespace

  def rpc_style(self, target):
    """Returns the style of RPC stub to generate.

    :param target: The target to extract the RPC stub style from.
    :type target: :class:`pants.backend.codegen.thrift.java.java_thrift_library.JavaThriftLibrary`
    :returns: The RPC stub style to generate.
    :rtype: string
    """
    self._check_target(target)
    return target.rpc_style or self._default_rpc_style

  def _check_target(self, target):
    if not isinstance(target, JavaThriftLibrary):
      raise ValueError('Can only determine defaults for JavaThriftLibrary targets, '
                       'given {} of type {}'.format(target, type(target)))

  def _tuple(self):
    return self._default_compiler, self._default_language, self._default_rpc_style

  def __hash__(self):
    return hash(self._tuple())

  def __eq__(self, other):
    return type(self) == type(other) and self._tuple() == other._tuple()
