# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.engine.rules import Rule
from pants.ng import passthru, source_partition, subsystem


def rules() -> tuple[Rule, ...]:
    return (
        *passthru.rules(),
        *source_partition.rules(),
        *subsystem.rules(),
    )
