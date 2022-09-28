# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.experimental.java.register import rules as java_rules
from pants.backend.openapi.codegen.java.rules import rules as java_codegen_rules


def target_types():
    return []


def rules():
    return [*java_rules(), *java_codegen_rules()]
