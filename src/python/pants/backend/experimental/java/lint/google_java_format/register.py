# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.java.lint.google_java_format import rules as fmt_rules
from pants.backend.java.lint.google_java_format import skip_field
from pants.jvm import jdk_rules, util_rules
from pants.jvm.goals import lockfile
from pants.jvm.resolve import coursier_fetch, jvm_tool


def rules():
    return [
        *fmt_rules.rules(),
        *skip_field.rules(),
        *jdk_rules.rules(),
        *lockfile.rules(),
        *jvm_tool.rules(),
        *coursier_fetch.rules(),
        *util_rules.rules(),
    ]
