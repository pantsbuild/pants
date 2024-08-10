# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.experimental.python.register import rules as python_rules
from pants.backend.experimental.python.register import target_types as python_target_types
from pants.backend.experimental.openapi.register import rules as openapi_rules
from pants.backend.experimental.openapi.register import target_types as openapi_target_types
from pants.backend.openapi.codegen.python.rules import rules as openapi_python_codegen_rules


def target_types():
    return [*python_target_types(), *openapi_target_types()]


def rules():
    return [*python_rules(), *openapi_rules(), *openapi_python_codegen_rules()]
