# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.binaries.binary_util import BinaryUtil
from pants.subsystem.subsystem import Subsystem
from pants.util.memo import memoized_property


class ThriftBinary(object):
  """Encapsulates access to pre-built thrift static binaries."""

  class Factory(Subsystem):
    options_scope = 'thrift-binary'

    @classmethod
    def subsystem_dependencies(cls):
      return (BinaryUtil.Factory,)

    @classmethod
    def register_options(cls, register):
      register('--supportdir', advanced=True, default='bin/thrift',
               help='Find thrift binaries under this dir.   Used as part of the path to lookup the'
                    'tool with --binary-util-baseurls and --pants-bootstrapdir')
      register('--version', advanced=True, default='0.9.2', fingerprint=True,
               help='Thrift compiler version.   Used as part of the path to lookup the'
                    'tool with --binary-util-baseurls and --pants-bootstrapdir')

    def create(self):
      # NB: create is an instance method to allow the user to choose global or scoped.
      # Its not unreasonable to imagine python and jvm stacks using different versions.
      binary_util = BinaryUtil.Factory.create()
      options = self.get_options()
      return ThriftBinary(binary_util, options.supportdir, options.version)

  def __init__(self, binary_util, relpath, version):
    self._binary_util = binary_util
    self._relpath = relpath
    self._version = version

  @property
  def version(self):
    """Returns the version of the thrift binary.

    :returns string version: The thrift version number string.
    """
    return self._version

  @memoized_property
  def path(self):
    """Selects a thrift compiler binary matching the current os and architecture.

    :returns: The absolute path to a locally bootstrapped thrift compiler binary.
    """
    return self._binary_util.select_binary(self._relpath, self.version, 'thrift')
