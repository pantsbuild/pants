# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.docker.lint.hadolint import register
from pants.base.deprecated import deprecated


@deprecated(
    "2.11.0.dev0",
    (
        "The `pants.backend.experimental.docker.lint.hadolint` backend has graduated. Use "
        "`pants.backend.docker.lint.hadolint` instead."
    ),
)
def rules():
    return register.rules()
