# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.binaries.binary_tool import NativeTool
from pants.binaries.thrift_binary import ThriftBinary


class Thrift(NativeTool):
  @classmethod
  def subsystem_dependencies(cls):
    # Ensure registration of the ThriftBinary.Factory, so that the thrift-binary
    # scope exists, for backwards compatibility during deprecation.
    return super(Thrift, cls).subsystem_dependencies() + (ThriftBinary.Factory,)

  options_scope = 'thrift'
  default_version = '0.9.2'

  replaces_scope = 'thrift-binary'
  replaces_name = 'version'
