# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from dataclasses import dataclass

import ijson.backends.python as ijson

from pants.backend.go.util_rules import go_mod
from pants.backend.go.util_rules.cgo import CGoCompilerFlags
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.engine.internals.selectors import Get
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GoStdLibPackage:
    name: str
    import_path: str
    pkg_source_path: str
    imports: tuple[str, ...]
    import_map: FrozenDict[str, str]

    # Analysis for when Pants is able to compile the SDK directly.
    go_files: tuple[str, ...]
    cgo_files: tuple[str, ...]
    c_files: tuple[str, ...]
    cxx_files: tuple[str, ...]
    m_files: tuple[str, ...]
    h_files: tuple[str, ...]
    f_files: tuple[str, ...]
    s_files: tuple[str, ...]
    syso_files: tuple[str, ...]
    cgo_flags: CGoCompilerFlags

    # Embed configuration.
    #
    # Note: `EmbedConfig` is not resolved here to avoid issues with trying to build the the embed analyzer.
    # The `EmbedConfig` will be resolved in `build_pkg_target.py` rules.
    embed_patterns: tuple[str, ...]
    embed_files: tuple[str, ...]


class GoStdLibPackages(FrozenDict[str, GoStdLibPackage]):
    """A mapping of standard library import paths to an analysis of the package at that import
    path."""


@dataclass(frozen=True)
class GoStdLibPackagesRequest:
    with_race_detector: bool
    cgo_enabled: bool = True


@rule(desc="Analyze Go standard library packages.", level=LogLevel.DEBUG)
async def analyze_go_stdlib_packages(request: GoStdLibPackagesRequest) -> GoStdLibPackages:
    maybe_race_arg = ["-race"] if request.with_race_detector else []
    list_result = await Get(
        ProcessResult,
        GoSdkProcess(
            # "-find" skips determining dependencies and imports for each package.
            command=("list", *maybe_race_arg, "-json", "std"),
            env={"CGO_ENABLED": "1" if request.cgo_enabled else "0"},
            description="Ask Go for its available import paths",
        ),
    )
    stdlib_packages = {}
    for pkg_json in ijson.items(list_result.stdout, "", multiple_values=True):
        import_path = pkg_json.get("ImportPath")
        pkg_source_path = pkg_json.get("Dir")

        if not import_path or not pkg_source_path:
            continue

        stdlib_packages[import_path] = GoStdLibPackage(
            name=pkg_json.get("Name"),
            import_path=import_path,
            pkg_source_path=pkg_source_path,
            imports=tuple(pkg_json.get("Imports", ())),
            import_map=FrozenDict(pkg_json.get("ImportMap", {})),
            go_files=tuple(pkg_json.get("GoFiles", ())),
            cgo_files=tuple(pkg_json.get("CgoFiles", ())),
            c_files=tuple(pkg_json.get("CFiles", ())),
            cxx_files=tuple(pkg_json.get("CXXFiles", ())),
            m_files=tuple(pkg_json.get("MFiles", ())),
            h_files=tuple(pkg_json.get("HFiles", ())),
            f_files=tuple(pkg_json.get("FFiles", ())),
            s_files=tuple(pkg_json.get("SFiles", ())),
            syso_files=tuple(pkg_json.get("SysoFiles", ())),
            cgo_flags=CGoCompilerFlags(
                cflags=tuple(pkg_json.get("CgoCFLAGS", [])),
                cppflags=tuple(pkg_json.get("CgoCPPFLAGS", [])),
                cxxflags=tuple(pkg_json.get("CgoCXXFLAGS", [])),
                fflags=tuple(pkg_json.get("CgoFFLAGS", [])),
                ldflags=tuple(pkg_json.get("CgoLDFLAGS", [])),
                pkg_config=tuple(pkg_json.get("CgoPkgConfig", [])),
            ),
            embed_patterns=tuple(pkg_json.get("EmbedPatterns", [])),
            embed_files=tuple(pkg_json.get("EmbedFiles", [])),
        )

    return GoStdLibPackages(stdlib_packages)


def rules():
    return (
        *collect_rules(),
        *go_mod.rules(),
    )
