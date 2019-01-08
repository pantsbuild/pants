# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField, PrimitivesSetField
from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants.util.memo import memoized_property


class NativePythonWheel(Target):

  @classmethod
  def alias(cls):
    return 'native_python_wheel'

  def __init__(self, requirement_target_spec, module_name, include_relpath, lib_relpath,
               native_lib_names, address=None, payload=None, **kwargs):

    self.address = address
    payload = payload or Payload()
    payload.add_fields({
      'requirement_target_spec': PrimitiveField(
        self._parse_requirement_target_spec(address, requirement_target_spec)),
      'module_name': PrimitiveField(module_name),
      'include_relpath': PrimitiveField(include_relpath),
      'lib_relpath': PrimitiveField(lib_relpath),
      'native_lib_names': PrimitivesSetField(native_lib_names),
    })
    super(NativePythonWheel, self).__init__(address=address, payload=payload, **kwargs)

  @staticmethod
  def _parse_requirement_target_spec(address, sources_target):
    return Address.parse(sources_target, relative_to=address.spec_path).spec

  @memoized_property
  def requirement_target(self):
    req_spec = self.payload.requirement_target_spec
    # Note: this requires the target spec to also be one of the transitive dependencies of the
    # target roots! This might be fine for now since native libraries are only accessible through
    # python_dist()s.
    req_target = self._build_graph.get_target_from_spec(req_spec)
    if not isinstance(req_target, PythonRequirementLibrary):
      raise TargetDefinitionException(
        self,
        "requirement_target_spec must point to a python_requirement_library() target! "
        "was: {} (type {})".format(req_spec, type(req_target).__name__))
    return req_target

  @property
  def module_name(self):
    return self.payload.module_name

  @property
  def include_relpath(self):
    return self.payload.include_relpath

  @property
  def lib_relpath(self):
    return self.payload.lib_relpath

  @property
  def native_lib_names(self):
    return self.payload.native_lib_names
