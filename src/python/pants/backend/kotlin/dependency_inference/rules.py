# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.kotlin.dependency_inference import kotlin_parser
from pants.engine.rules import collect_rules


def rules():
    return (
        *collect_rules(),
        *kotlin_parser.rules(),
    )
