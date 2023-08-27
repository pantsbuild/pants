# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.javascript.subsystems import nodejs
from pants.backend.openapi.lint.openapi_format import rules as openapi_format_rules
from pants.backend.openapi.lint.openapi_format import skip_field


def rules():
    return (*nodejs.rules(), *openapi_format_rules.rules(), *skip_field.rules())
