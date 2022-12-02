# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.tools.fmt.preamble import rules as preamble_rules


def rules():
    return [
        *preamble_rules.rules(),
    ]
