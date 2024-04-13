# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.experimental.go.register import rules as go_backend_rules
from pants.backend.experimental.go.register import target_types as go_target_types_func
from pants.backend.go.goals import debug_goals


def target_types():
    return go_target_types_func()


def rules():
    return (
        *debug_goals.rules(),
        *go_backend_rules(),
    )
