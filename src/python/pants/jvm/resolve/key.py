# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.engine.fs import Digest


@dataclass(frozen=True)
class CoursierResolveKey:
    name: str
    path: str
    digest: Digest
