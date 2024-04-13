# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.tools.taplo import rules as taplo_rules


def rules():
    return [
        *taplo_rules.rules(),
    ]
