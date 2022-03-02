# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.docker.lint.hadolint import skip_field
from pants.backend.docker.lint.hadolint.rules import rules as hadolint_rules
from pants.backend.docker.rules import rules as docker_rules


def rules():
    return (
        *docker_rules(),
        *hadolint_rules(),
        *skip_field.rules(),
    )
