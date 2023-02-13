# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.javascript.subsystems import nodejs
from pants.backend.openapi.lint.spectral import rules as spectral_rules
from pants.backend.openapi.lint.spectral import skip_field


def rules():
    return (*nodejs.rules(), *spectral_rules.rules(), *skip_field.rules())
