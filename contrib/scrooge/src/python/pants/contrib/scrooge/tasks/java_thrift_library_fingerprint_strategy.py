# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib

from future.utils import PY3
from pants.backend.codegen.thrift.java.java_thrift_library import JavaThriftLibrary
from pants.base.fingerprint_strategy import FingerprintStrategy


class JavaThriftLibraryFingerprintStrategy(FingerprintStrategy):
  """Scrooge cares about a Thrift target's `language` and `compiler_args` and more in addition to
  its payload.

  As such this strategy ensures new code is generated by Scrooge whenever any option that effects
  codegen changes.
  """

  def __init__(self, thrift_defaults):
    self._thrift_defaults = thrift_defaults

  def compute_fingerprint(self, target):
    fp = target.payload.fingerprint()
    if not isinstance(target, JavaThriftLibrary):
      return fp

    hasher = hashlib.sha1()
    hasher.update(fp.encode('utf-8'))
    hasher.update(self._thrift_defaults.language(target).encode('utf-8'))
    hasher.update(str(self._thrift_defaults.compiler_args(target)).encode('utf-8'))

    namespace_map = self._thrift_defaults.namespace_map(target)
    if namespace_map:
      hasher.update(str(sorted(namespace_map.items())).encode('utf-8'))

    default_java_namespace = self._thrift_defaults.default_java_namespace(target)
    if default_java_namespace:
      hasher.update(default_java_namespace.encode('utf-8'))

    if target.include_paths:
      hasher.update(str(target.include_paths).encode('utf-8'))

    return hasher.hexdigest() if PY3 else hasher.hexdigest().decode('utf-8')

  def __hash__(self):
    return hash((type(self), self._thrift_defaults))

  def __eq__(self, other):
    return type(self) == type(other) and self._thrift_defaults == other._thrift_defaults
