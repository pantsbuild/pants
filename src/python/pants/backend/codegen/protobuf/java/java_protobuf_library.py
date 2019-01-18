# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import logging

from pants.backend.jvm.targets.import_jars_mixin import ImportJarsMixin
from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.deprecated import deprecated_conditional
from pants.base.payload import Payload
from pants.base.payload_field import PrimitiveField


logger = logging.getLogger(__name__)


class JavaProtobufLibrary(ImportJarsMixin, JvmTarget):
  """A Java library generated from Protocol Buffer IDL files."""

  imported_target_kwargs_field = 'imports'
  imported_target_payload_field = 'import_specs'

  def __init__(self, payload=None, buildflags=None, imports=None, **kwargs):
    """
    :param buildflags: Unused, and will be removed in a future release.
    :param list imports: List of addresses of `jar_library <#jar_library>`_
      targets which contain .proto definitions.
    """
    payload = payload or Payload()
    deprecated_conditional(
      lambda: imports is not None,
      '1.16.0.dev1',
      "{cls} target definition at {addr} setting attribute 'imports'"
      .format(cls=type(self).__name__, addr=self.address.spec),
      hint_message="Use a combination of remote_sources() and unpacked_jars() instead.")
    # TODO(Eric Ayers): The target needs to incorporate the settings of --gen-protoc-version
    # and --gen-protoc-plugins into the fingerprint.  Consider adding a custom FingeprintStrategy
    # into ProtobufGen to get it.
    payload.add_fields({
      'import_specs': PrimitiveField(imports or ())
    })
    super(JavaProtobufLibrary, self).__init__(payload=payload, **kwargs)

    deprecated_conditional(
      lambda: buildflags is not None,
      '1.16.0.dev1',
      "{cls} target definition at {addr} setting attribute 'buildflags'"
      .format(cls=type(self).__name__, addr=self.address.spec),
      hint_message="Use the options denoted in `./pants help gen.protoc` instead.")
