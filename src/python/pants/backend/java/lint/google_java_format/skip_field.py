# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.java.target_types import JavaSourceField, JavaSourceTarget
from pants.engine.target import BoolField


class SkipGoogleJavaFormatField(BoolField):
    alias = "skip_google_java_format"
    default = False
    help = "If true, don't run Google Java Format on this target's code."


def rules():
    return [JavaSourceTarget.register_plugin_field(JavaSourceField)]
