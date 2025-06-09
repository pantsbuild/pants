# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

"""TypeScript type checking."""

from pants.backend.typescript.check import rules as check_rules


def rules():
    return [
        *check_rules(),
    ]