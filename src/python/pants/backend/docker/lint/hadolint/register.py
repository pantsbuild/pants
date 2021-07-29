# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.docker.lint.hadolint import skip_field
from pants.backend.docker.lint.hadolint.rules import rules as hadolint_rules


def rules():
    return (
        *hadolint_rules(),
        *skip_field.rules(),
    )
