# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

DEFAULT = object()
SKIP = object()

JVM_ARTIFACT_MAPPINGS = {
    "org": {
        "joda": {
            "time": "joda-time:joda-time",
        },
        "junit": "junit:junit",
    },
}
