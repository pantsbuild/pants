# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.native.targets.native_artifact import NativeArtifact
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField
from pants.build_graph.target import Target


class NativeLibrary(Target):
  """A class wrapping targets containing sources for C-family languages and related code."""

  @classmethod
  def produces_ctypes_dylib(cls, target):
    return isinstance(target, cls) and bool(target.ctypes_dylib)

  def __init__(self, address, payload=None, sources=None, ctypes_dylib=None,
               strict_deps=None, fatal_warnings=None, **kwargs):

    if not payload:
      payload = Payload()
    sources_field = self.create_sources_field(sources, address.spec_path, key_arg='sources')
    payload.add_fields({
      'sources': sources_field,
      'ctypes_dylib': ctypes_dylib,
      'strict_deps': PrimitiveField(strict_deps),
      'fatal_warnings': PrimitiveField(fatal_warnings),
    })

    if ctypes_dylib and not isinstance(ctypes_dylib, NativeArtifact):
      raise TargetDefinitionException(
        "Target must provide a valid pants '{}' object. Received an object with type '{}' "
        "and value: {}."
        .format(NativeArtifact.alias(), type(ctypes_dylib).__name__, ctypes_dylib))

    super(NativeLibrary, self).__init__(address=address, payload=payload, **kwargs)

  @property
  def strict_deps(self):
    return self.payload.strict_deps

  @property
  def fatal_warnings(self):
    return self.payload.fatal_warnings

  @property
  def ctypes_dylib(self):
    return self.payload.ctypes_dylib


class CLibrary(NativeLibrary):

  default_sources_globs = [
    '*.h',
    '*.c',
  ]

  @classmethod
  def alias(cls):
    return 'ctypes_compatible_c_library'


class CppLibrary(NativeLibrary):

  default_sources_globs = [
    '*.h',
    '*.hpp',
    '*.cpp',
  ]

  @classmethod
  def alias(cls):
    return 'ctypes_compatible_cpp_library'
