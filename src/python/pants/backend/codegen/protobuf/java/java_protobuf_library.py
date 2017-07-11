# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import logging

from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField


logger = logging.getLogger(__name__)


class JavaProtobufLibrary(ImportJarsMixin, JvmTarget):
  """A Java library generated from Protocol Buffer IDL files."""

  def __init__(self, payload=None, buildflags=None, imports=None, **kwargs):
    """
    :param buildflags: Unused, and will be removed in a future release.
    :param list imports: List of addresses of `jar_library <#jar_library>`_
      targets which contain .proto definitions.
    """
    payload = payload or Payload()
    # TODO(Eric Ayers): The target needs to incorporate the settings of --gen-protoc-version
    # and --gen-protoc-plugins into the fingerprint.  Consider adding a custom FingeprintStrategy
    # into ProtobufGen to get it.
    payload.add_fields({
      'import_specs': PrimitiveField(imports or ())
    })
    super(JavaProtobufLibrary, self).__init__(payload=payload, **kwargs)
    if buildflags is not None:
      logger.warn("Target definition at {address} sets attribute 'buildflags' which is "
                  "ignored and will be removed in a future release"
                  .format(address=self.address.spec))

  @classmethod
  def imported_jar_library_spec_fields(cls):
    """Fields to extract JarLibrary specs from.

    Required to implement the ImportJarsMixin.
    """
    yield ('imports', 'import_specs')
