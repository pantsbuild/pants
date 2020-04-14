# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.rules.targets import COMMON_JVM_FIELDS
from pants.engine.target import Sources, Target


class JavaProtobufLibrary(Target):
    """A Java library generated from Protocol Buffer IDL files."""

    alias = "java_protobuf_library"
    core_fields = (*COMMON_JVM_FIELDS, Sources)
    v1_only = True
