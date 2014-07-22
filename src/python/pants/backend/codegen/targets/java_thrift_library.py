# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.config import Config
from pants.base.exceptions import TargetDefinitionException


class JavaThriftLibrary(JvmTarget):
  """Generates a stub Java or Scala library from thrift IDL files."""

  class Defaults(object):
    @staticmethod
    def _check_java_thrift_library(target):
      if not isinstance(target, JavaThriftLibrary):
        raise ValueError('Expected a JavaThriftLibrary, got: %s of type %s' % (target, type(target)))

    def __init__(self, config=None):
      self._config = config or Config.load()

    def _get_default(self, key, fallback):
      return self._config.get('java-thrift-library', key, default=fallback)

    def get_compiler(self, target):
      self._check_java_thrift_library(target)
      return target.compiler or self._get_default('compiler', 'thrift')

    def get_language(self, target):
      self._check_java_thrift_library(target)
      return target.language or self._get_default('language', 'java')

    def get_rpc_style(self, target):
      self._check_java_thrift_library(target)
      return target.rpc_style or self._get_default('rpc_style', 'sync')


  # TODO(John Sirois): Tasks should register the values they support in a plugin-registration phase.
  # In general a plugin will contribute a target and a task, but in this case we have a shared
  # target that can be used by at least 2 tasks - ThriftGen and ScroogeGen.  This is likely not
  # uncommon (gcc & clang) so the arrangement needs to be cleaned up and supported well.
  _COMPILERS = frozenset(['thrift', 'scrooge'])
  _LANGUAGES = frozenset(['java', 'scala'])
  _RPC_STYLES = frozenset(['sync', 'finagle', 'ostrich'])

  def __init__(self,
               compiler=None,
               language=None,
               rpc_style=None,
               namespace_map=None,
               **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param sources: Source code files to compile. Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings
    :param provides: The ``artifact``
      to publish that represents this target outside the repo.
    :param dependencies: Other targets that this target depends on.
    :type dependencies: list of target specs
    :param excludes: List of :ref:`exclude <bdict_exclude>`\s
      to filter this target's transitive dependencies against.
    :param compiler: The compiler used to compile the thrift files; default is 'thrift'
      (The apache thrift compiler).
    :param language: The language used to generate the output files; defaults to 'java'.
    :param rpc_style: An optional rpc style to generate service stubs with.
    :param namespace_map: An optional dictionary of namespaces to remap {old: new}
    :param exclusives: An optional map of exclusives tags. See CheckExclusives for details.
    """

    # It's critical that provides is set 1st since _provides() is called elsewhere in the
    # constructor flow.
    # TODO(pl): Above is defunct?
    # self._provides = provides

    super(JavaThriftLibrary, self).__init__(**kwargs)

    self.add_labels('codegen')

    def check_value_for_arg(arg, value, values):
      if value is not None and value not in values:
        raise TargetDefinitionException(self, "%s may only be set to %s ('%s' not valid)" %
                                        (arg, ', or '.join(map(repr, values)), value))
      return value

    self.compiler = check_value_for_arg('compiler', compiler, self._COMPILERS)
    self.language = check_value_for_arg('language', language, self._LANGUAGES)
    self.rpc_style = check_value_for_arg('rpc_style', rpc_style, self._RPC_STYLES)

    self.namespace_map = namespace_map

  @property
  def is_thrift(self):
    return True
