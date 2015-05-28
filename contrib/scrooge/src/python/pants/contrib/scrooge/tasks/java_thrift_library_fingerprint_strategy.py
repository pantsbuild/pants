# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import hashlib

from pants.backend.codegen.targets.java_thrift_library import JavaThriftLibrary
from pants.base.fingerprint_strategy import FingerprintStrategy


class JavaThriftLibraryFingerprintStrategy(FingerprintStrategy):
  """
  JavaThriftLibrary fingerprint strategy was added so that scrooge fields will only be part
  of the fingerprint when they are used.
  """
  def __init__(self, options):
    self._options = options

  def compute_fingerprint(self, target):
    """java_thrift_library needs to include compiler, language and rpc_style in
       its fingerprint.
    """
    fp = target.payload.fingerprint()
    if not isinstance(target, JavaThriftLibrary):
      return fp

    hasher = hashlib.sha1()
    hasher.update(fp)
    hasher.update(target.compiler or self._options.for_global_scope().thrift_default_compiler)
    hasher.update(target.language or self._options.for_global_scope().thrift_default_language)
    hasher.update(target.rpc_style or self._options.for_global_scope().thrift_default_rpc_style)
    return hasher.hexdigest()

  def __hash__(self):
    return hash((type(self), self._options))

  def __eq__(self, other):
    return type(self) == type(other) and self._options == other._options
