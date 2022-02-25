# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pants.bsp.spec.base import Uri


@dataclass(frozen=True)
class JvmBuildTarget:
    # Uri representing absolute path to jdk
    # For example: file:///usr/lib/jvm/java-8-openjdk-amd64
    java_home: Uri | None = None

    # The java version this target is supposed to use.
    # For example: 1.8
    java_version: str | None = None

    @classmethod
    def from_json_dict(cls, d: dict[str, Any]) -> Any:
        return cls(
            java_home=d.get("javaHome"),
            java_version=d.get("javaVersion"),
        )

    def to_json_dict(self) -> dict[str, Any]:
        result = {}
        if self.java_home is not None:
            result["javaHome"] = self.java_home
        if self.java_version is not None:
            result["javaVersion"] = self.java_version
        return result
