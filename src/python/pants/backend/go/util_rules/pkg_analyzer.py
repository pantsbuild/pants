# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.go.go_sources import load_go_binary
from pants.backend.go.go_sources.load_go_binary import LoadedGoBinary, LoadedGoBinaryRequest
from pants.engine.fs import Digest
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule


@dataclass(frozen=True)
class PackageAnalyzerSetup:
    digest: Digest
    path: str


@rule
async def setup_go_package_analyzer() -> PackageAnalyzerSetup:
    binary_path = "./package_analyzer"
    binary = await Get(
        LoadedGoBinary,
        LoadedGoBinaryRequest("analyze_package", ("main.go", "read.go"), binary_path),
    )
    return PackageAnalyzerSetup(
        digest=binary.digest,
        path=binary_path,
    )


def rules():
    return (
        *collect_rules(),
        *load_go_binary.rules(),
    )
