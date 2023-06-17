# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.nfpm.util_rules.generate_config import rules as generate_config_rules
from pants.backend.nfpm.util_rules.sandbox import rules as sandbox_rules
from pants.engine.rules import collect_rules


def rules():
    return [
        *generate_config_rules(),
        *sandbox_rules(),
        *collect_rules(),
    ]
