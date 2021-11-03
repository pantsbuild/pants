# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import pkgutil
from dataclasses import dataclass
from typing import ClassVar

import ijson

from pants.backend.go.util_rules.build_pkg import BuildGoPackageRequest, BuiltGoPackage
from pants.backend.go.util_rules.import_analysis import ImportConfig, ImportConfigRequest
from pants.backend.go.util_rules.link import LinkedGoBinary, LinkGoBinaryRequest
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class AnalyzeGoPackagesRequest:
    digest: Digest
    paths: tuple[str, ...]


@dataclass(frozen=True)
class AnalyzedGoPackage:
    name: str
    imports: tuple[str, ...]
    test_imports: tuple[str, ...]
    xtest_imports: tuple[str, ...]
    go_files: tuple[str, ...]
    s_files: tuple[str, ...]

    ignored_go_files: tuple[str, ...]
    ignored_other_files: tuple[str, ...]

    test_go_files: tuple[str, ...]
    xtest_go_files: tuple[str, ...]

    invalid_go_files: FrozenDict[str, str]
    error: str | None

    @classmethod
    def from_json_dict(cls, d):
        return cls(
            name=d["name"],
            imports=tuple(d.get("imports", ())),
            test_imports=tuple(d.get("test_imports", ())),
            xtest_imports=tuple(d.get("xtest_imports", ())),
            go_files=tuple(d.get("go_files", ())),
            s_files=tuple(d.get("s_files", ())),
            ignored_go_files=tuple(d.get("ignored_go_files", ())),
            ignored_other_files=tuple(d.get("ignored_other_files", ())),
            test_go_files=tuple(d.get("test_go_files", ())),
            xtest_go_files=tuple(d.get("xtest_go_files", ())),
            invalid_go_files=FrozenDict(d.get("invalid_go_files", {})),
            error=d.get("error"),
        )


@dataclass(frozen=True)
class AnalyzedGoPackages:
    packages: FrozenDict[str, AnalyzedGoPackage]


@dataclass(frozen=True)
class AnalyzerSetup:
    digest: Digest
    PATH: ClassVar[str] = "./analyze_package"


@rule
async def setup_analyzer() -> AnalyzerSetup:
    source_entry_content = pkgutil.get_data("pants.backend.go.util_rules", "analyze_package.go")
    if not source_entry_content:
        raise AssertionError("Unable to find resource for `generate_testmain.go`.")

    source_entry = FileContent("generate_testmain.go", source_entry_content)

    source_digest, import_config = await MultiGet(
        Get(Digest, CreateDigest([source_entry])),
        Get(ImportConfig, ImportConfigRequest, ImportConfigRequest.stdlib_only()),
    )

    built_analyzer_pkg = await Get(
        BuiltGoPackage,
        BuildGoPackageRequest(
            import_path="main",
            subpath="",
            digest=source_digest,
            go_file_names=(source_entry.path,),
            s_file_names=(),
            direct_dependencies=(),
            minimum_go_version=None,
        ),
    )
    main_pkg_a_file_path = built_analyzer_pkg.import_paths_to_pkg_a_files["main"]
    input_digest = await Get(
        Digest, MergeDigests([built_analyzer_pkg.digest, import_config.digest])
    )

    analyzer = await Get(
        LinkedGoBinary,
        LinkGoBinaryRequest(
            input_digest=input_digest,
            archives=(main_pkg_a_file_path,),
            import_config_path=import_config.CONFIG_PATH,
            output_filename=AnalyzerSetup.PATH,
            description="Link Go package analyzer",
        ),
    )

    return AnalyzerSetup(analyzer.digest)


@rule
async def analyze_go_package(
    request: AnalyzeGoPackagesRequest, analyzer: AnalyzerSetup
) -> AnalyzedGoPackages:
    assert len(request.paths) > 0

    input_digest = await Get(Digest, MergeDigests([request.digest, analyzer.digest]))

    result = await Get(
        ProcessResult,
        Process(
            argv=(analyzer.PATH, *request.paths),
            input_digest=input_digest,
            description=f"Analyze Go packages for {', '.join(request.paths)}",
            level=LogLevel.DEBUG,
        ),
    )

    assert len(result.stdout) != 0
    packages: dict[str, AnalyzedGoPackage] = {}
    for i, data in enumerate(ijson.items(result.stdout, "", multiple_values=True)):
        packages[request.paths[i]] = AnalyzedGoPackage.from_json_dict(data)

    return AnalyzedGoPackages(FrozenDict(packages))


def rules():
    return collect_rules()
