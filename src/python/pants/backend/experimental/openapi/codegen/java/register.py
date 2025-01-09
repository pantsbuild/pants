# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.experimental.java.register import rules as java_rules
from pants.backend.experimental.java.register import target_types as java_target_types
from pants.backend.experimental.openapi.register import rules as openapi_rules
from pants.backend.experimental.openapi.register import target_types as openapi_target_types
from pants.backend.openapi.codegen.java.rules import rules as openapi_java_codegen_rules


def target_types():
    return [*java_target_types(), *openapi_target_types()]


def rules():
    return [*java_rules(), *openapi_rules(), *openapi_java_codegen_rules()]
