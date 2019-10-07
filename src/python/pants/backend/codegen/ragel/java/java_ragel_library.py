# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.jvm.targets.jvm_target import JvmTarget


class JavaRagelLibrary(JvmTarget):
    """A Java library generated from a Ragel file."""
