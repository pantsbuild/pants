# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

from pex.interpreter import PythonIdentity
from twitter.common.collections import maybe_list

from pants.backend.python.targets.python_requirement_library import PythonRequirementLibrary
from pants.base.exceptions import TargetDefinitionException
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField, PrimitivesSetField
from pants.build_graph.address import Address
from pants.build_graph.target import Target
from pants.util.memo import memoized_property


class NativePythonWheel(Target):
  """Specify how to pull native code out of a module in a `PythonRequirementLibrary` target.

  This target can be depended on by C and C++ source targets to provide headers and/or libraries to
  link against.
  """

  @classmethod
  def alias(cls):
    return 'native_python_wheel'

  def __init__(self, requirement_target_spec, module_name, include_relpath, lib_relpath,
               native_lib_names, compatibility=None, address=None, payload=None, **kwargs):
    """
    :param requirement_target_spec: Address for an existing ``python_requirement_library()``
                                    target. This target is resolved into a pex which the native
                                    resources are extracted from.
    :param module_name: The name of the specific python module containing headers and/or libraries
                        to extract (e.g. 'tensorflow').
    :param include_relpath: The relative path from the wheel's data directory to the root directory
                            where C/C++ header files are located. Use ``''`` if located in the
                            top-level directory.
    :param lib_relpath: The relative path from the wheel's data directory to the single directory
                        where native libraries are located. Use ``''`` if located in the top-level
                        directory.
    :param native_lib_names: Names of any native libraries contained in the wheel. For a library
                        named ``libmylib.so``, use the name ``mylib``.
    :param compatibility: Python interpreter constraints used to create the pex for the requirement
                          target. If unset, the default interpreter constraints are used. This
                          argument is unnecessary unless the native code depends on libpython.
    """

    self.address = address
    payload = payload or Payload()
    payload.add_fields({
      'requirement_target_spec': PrimitiveField(
        self._parse_requirement_target_spec(address, requirement_target_spec)),
      'module_name': PrimitiveField(module_name),
      'include_relpath': PrimitiveField(include_relpath),
      'lib_relpath': PrimitiveField(lib_relpath),
      'native_lib_names': PrimitivesSetField(native_lib_names),
      'compatibility': PrimitiveField(maybe_list(compatibility or ())),
    })
    super(NativePythonWheel, self).__init__(address=address, payload=payload, **kwargs)

    # Check that the compatibility requirements are well-formed.
    # TODO: Introduce a mixin to validate compatibility requirements instead of assuming only
    # PythonTarget and PythonRequirementLibrary in
    # PythonInterpreterCache#partition_targets_by_compatibility()!
    for req in self.payload.compatibility:
      try:
        PythonIdentity.parse_requirement(req)
      except ValueError as e:
        raise TargetDefinitionException(self, str(e))

  @staticmethod
  def _parse_requirement_target_spec(address, sources_target):
    return Address.parse(sources_target, relative_to=address.spec_path).spec

  @memoized_property
  def requirement_target(self):
    req_spec = self.payload.requirement_target_spec
    # Note: using .get_target_from_spec() requires the target spec to also be one of the transitive
    # dependencies of the target roots! This might be fine for now since native libraries are only
    # accessible through python_dist()s.
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

  @property
  def compatibility(self):
    return self.payload.compatibility
