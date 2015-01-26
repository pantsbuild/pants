# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import logging
import six

from pants.backend.jvm.targets.exportable_jvm_library import ExportableJvmLibrary
from pants.backend.jvm.targets.jar_library import JarLibrary

from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField

logger = logging.getLogger(__name__)


class JavaProtobufLibrary(ExportableJvmLibrary):
  """Generates a stub Java library from protobuf IDL files."""

  def __init__(self, payload=None, buildflags=None, imports=None, **kwargs):
    """
    :param buildflags: Unused, and will be removed in a future release.
    :param list imports: List of addresses of `jar_library <#jar_library>`_
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
    """Returns the set of JarDependency instances to be included when compiling this target."""
    if self._imports is None:
      self._imports = JarLibrary.to_jar_dependencies(self.address,
                                                     self.payload.raw_imports,
                                                     self._build_graph)
    return self._imports
