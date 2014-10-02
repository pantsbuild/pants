# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import logging
import six

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.base.address import SyntheticAddress
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField

logger = logging.getLogger(__name__)


class JavaProtobufLibrary(ExportableJvmLibrary):
  """Generates a stub Java library from protobuf IDL files."""

  class PrematureImportPokeError(Exception):
    """Thrown if something tries to access this target's imports before the build graph has been
    generated.
    """
  class WrongTargetTypeError(Exception):
    """Thrown if a reference to a non jar_library is added to an import attribute.
    """

  class ExpectedAddressError(Exception):
    """Thrown if an object that is not an address is added to an import attribute.
    """

  def __init__(self, payload=None, buildflags=None, imports=None, **kwargs):
    """
    :param buildflags: Unused, and will be removed in a future release.
    :param imports: List of addresses of :class:`pants.backend.jvm.targets.jar_library.JarLibrary`
      targets which contain .proto definitions.
    """
    payload = payload or Payload()
    payload.add_fields({
      'raw_imports': PrimitiveField(imports or ())
    })
    super(JavaProtobufLibrary, self).__init__(payload=payload, **kwargs)
    if buildflags is not None:
      logger.warn(" Target definition at {address} sets attribute 'buildflags' which is "
                  "ignored and will be removed in a future release"
                  .format(address=self.address.spec))
    self.add_labels('codegen')
    if imports:
      self.add_labels('has_imports')
    self._imports = None

  @property
  def traversable_specs(self):
    for spec in super(JavaProtobufLibrary, self).traversable_specs:
      yield spec
    if self.payload.raw_imports:
      for spec  in self.payload.raw_imports:
        # This simply skips over non-strings, but we catch them with a WrongTargetType below.
        if isinstance(spec, six.string_types):
          yield spec

  @property
  def imports(self):
    """Returns the set of JarDependencys to be included when compiling this target."""
    if self._imports is None:
      import_jars = set()
      for spec in self.payload.raw_imports:
        if not isinstance(spec, six.string_types):
          raise self.ExpectedAddressError(
            "{address}: expected imports to contain string addresses, got {found_class}."
            .format(address=self.address.spec,
                    found_class=spec.__class__.__name__))
        address = SyntheticAddress.parse(spec, relative_to=self.address.spec_path)
        target = self._build_graph.get_target(address)
        if isinstance(target, JarLibrary):
          import_jars.update(target.jar_dependencies)
        elif target is None:
          # TODO(pl, zundel): Not sure if we can ever reach this case. An address that
          # can't be resolved is caught when resolving the build graph.
          raise self.PrematureImportPokeError(
            "Internal Error: {address}: Failed to resolve import '{spec}'".format(
              address=self.address.spec,
              spec=address.spec))
        else:
          raise self.WrongTargetTypeError(
            "{address}: expected {spec} to be jar_library target type, got {found_class}"
            .format(address=self.address.spec,
                    spec=address.spec,
                    found_class=target.__class__.__name__))

      self._imports = list(import_jars)
    return self._imports
