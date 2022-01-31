# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.docker import register
from pants.base.deprecated import deprecated


@deprecated(
    "2.11.0.dev0",
    "The `pants.backend.experimental.docker` backend has graduated. Use `pants.backend.docker` instead.",
)
def rules():
    return register.rules()


def target_types():
    return register.target_types()
