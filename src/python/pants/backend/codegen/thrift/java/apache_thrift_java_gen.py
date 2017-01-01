# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.backend.codegen.thrift.java.thrift_defaults import ThriftDefaults
from pants.backend.codegen.thrift.lib.apache_thrift_gen_base import ApacheThriftGenBase
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.exceptions import TargetDefinitionException
from pants.binaries.thrift_binary import ThriftBinary


class ApacheThriftJavaGen(ApacheThriftGenBase):
  deprecated_options_scope = 'gen.thrift'  # New scope is gen.thrift-java.
  deprecated_options_scope_removal_version = '1.5.0'

  thrift_library_target_type = JavaThriftLibrary
  thrift_generator = 'java'

  _COMPILER = 'thrift'
  _RPC_STYLE = 'sync'

  @classmethod
  def subsystem_dependencies(cls):
    return (super(ApacheThriftJavaGen, cls).subsystem_dependencies() +
            (ThriftDefaults, ThriftBinary.Factory.scoped(cls)))

  @classmethod
  def implementation_version(cls):
    return super(ApacheThriftJavaGen, cls).implementation_version() + [('ApacheThriftGen', 2)]

  def __init__(self, *args, **kwargs):
    super(ApacheThriftJavaGen, self).__init__(*args, **kwargs)
    self._thrift_defaults = ThriftDefaults.global_instance()

  def synthetic_target_type(self, target):
    return JavaLibrary

  def is_gentarget(self, target):
    return (super(ApacheThriftJavaGen, self).is_gentarget(target) and
            self._thrift_defaults.compiler(target) == self._COMPILER)

  def _validate(self, target):
    # TODO: Fix ThriftDefaults to only pertain to scrooge (see TODO there) and then
    # get rid of this spurious validation.
    if self._thrift_defaults.language(target) != self.thrift_generator:
      raise TargetDefinitionException(
          target,
          'Compiler {} supports only language={}.'.format(self._COMPILER, self.thrift_generator))
    if self._thrift_defaults.rpc_style(target) != self._RPC_STYLE:
      raise TargetDefinitionException(
          target,
          'Compiler {} supports only rpc_style={}.'.format(self._COMPILER, self._RPC_STYLE))

  def execute_codegen(self, target, target_workdir):
    self._validate(target)
    super(ApacheThriftJavaGen, self).execute_codegen(target, target_workdir)
