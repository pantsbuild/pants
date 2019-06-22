# Copyright 2017 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.jvm_target import JvmTarget
from pants.base.payload import Payload


class JavaAvroLibrary(JvmTarget):
  """Defines a target that builds Java code from Avro schema, protocol, or IDL files."""

  def __init__(self, payload=None, **kwargs):
    payload = payload or Payload()
    super().__init__(payload=payload, **kwargs)

  @classmethod
  def alias(cls):
    return 'java_avro_library'
