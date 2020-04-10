# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.rules.targets import COMMON_JVM_FIELDS
from pants.engine.target import Sources, Target


class JavaRagelLibrary(Target):
    """A Java library generated from a Ragel file."""

    alias = "java_ragel_library"
    core_fields = (*COMMON_JVM_FIELDS, Sources)
    v1_only = True
