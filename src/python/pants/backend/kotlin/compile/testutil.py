# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

_KOTLIN_VERSION = "1.6.20"
KOTLIN_STDLIB_REQUIREMENTS = [
    f"org.jetbrains.kotlin:kotlin-stdlib:{_KOTLIN_VERSION}",
    f"org.jetbrains.kotlin:kotlin-reflect:{_KOTLIN_VERSION}",
    f"org.jetbrains.kotlin:kotlin-script-runtime:{_KOTLIN_VERSION}",
]
