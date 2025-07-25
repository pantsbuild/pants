# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.go.go_sources import load_go_binary
from pants.backend.go.go_sources.load_go_binary import LoadedGoBinaryRequest, setup_go_binary
from pants.backend.go.util_rules.goroot import GoRoot
from pants.engine.fs import Digest
from pants.engine.rules import collect_rules, implicitly, rule


@dataclass(frozen=True)
class PackageAnalyzerSetup:
    digest: Digest
    path: str


@rule
async def setup_go_package_analyzer(goroot: GoRoot) -> PackageAnalyzerSetup:
    binary_path = "./package_analyzer"
    sources = (
        "main.go",
        "read.go",
        "build_context.go",
        "string_utils.go",
        "syslist.go",
        "tags.go1.17.go" if goroot.is_compatible_version("1.17") else "tags.go",
    )
    binary = await setup_go_binary(
        LoadedGoBinaryRequest(
            "analyze_package",
            sources,
            binary_path,
        ),
        **implicitly(),
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
