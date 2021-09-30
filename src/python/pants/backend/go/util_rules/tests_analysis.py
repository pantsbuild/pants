# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import pkgutil
from dataclasses import dataclass

from pants.backend.go.util_rules.compile import CompiledGoSources, CompileGoSourcesRequest
from pants.backend.go.util_rules.import_analysis import GatheredImports, GatherImportsRequest
from pants.backend.go.util_rules.link import LinkedGoBinary, LinkGoBinaryRequest
from pants.engine.fs import CreateDigest, Digest, FileContent, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class AnalyzeTestSourcesRequest:
    digest: Digest
    paths: FrozenOrderedSet[str]


@dataclass(frozen=True)
class GoTestCase:
    name: str
    package: str

    @classmethod
    def from_json_dict(cls, data: dict) -> GoTestCase:
        return cls(name=data["name"], package=data["package"])


@dataclass(frozen=True)
class AnalyzedTestSources:
    tests: FrozenOrderedSet[GoTestCase]
    benchmarks: FrozenOrderedSet[GoTestCase]
    has_test_main: bool

    @classmethod
    def from_json_dict(cls, data: dict) -> AnalyzedTestSources:
        def ensure_list(xs):
            return xs if xs is not None else []

        return cls(
            tests=FrozenOrderedSet(
                [GoTestCase.from_json_dict(d) for d in ensure_list(data.get("tests", []))]
            ),
            benchmarks=FrozenOrderedSet(
                [GoTestCase.from_json_dict(d) for d in ensure_list(data.get("benchmarks", []))]
            ),
            has_test_main=data["has_test_main"],
        )


@dataclass(frozen=True)
class AnalyzerSetup:
    digest: Digest
    path: str


@rule
async def setup_analyzer() -> AnalyzerSetup:
    source_entry_content = pkgutil.get_data(
        "pants.backend.go.util_rules", "analyze_test_sources.go"
    )
    if not source_entry_content:
        raise ValueError("Unable to find resouce for `analyze_test_sources.go`.")

    source_entry = FileContent(
        "analyze_test_sources.go",
        source_entry_content,
    )

    source_digest, imports = await MultiGet(
        Get(Digest, CreateDigest([source_entry])),
        Get(
            GatheredImports, GatherImportsRequest(packages=FrozenOrderedSet(), include_stdlib=True)
        ),
    )

    input_digest = await Get(Digest, MergeDigests([source_digest, imports.digest]))

    compiled_analyzer = await Get(
        CompiledGoSources,
        CompileGoSourcesRequest(
            digest=input_digest,
            sources=(source_entry.path,),
            import_path="main",
            description="Compile Go test sources analyzer.",
            import_config_path="./importcfg",
        ),
    )

    link_input_digest = await Get(
        Digest, MergeDigests([compiled_analyzer.output_digest, imports.digest])
    )

    analyzer = await Get(
        LinkedGoBinary,
        LinkGoBinaryRequest(
            input_digest=link_input_digest,
            archives=("__pkg__.a",),
            import_config_path="./importcfg",
            output_filename="./analyzer",
            description="Link Go test sources analyzer.",
        ),
    )

    return AnalyzerSetup(digest=analyzer.output_digest, path="./analyzer")


@rule
async def analyze_test_sources(
    request: AnalyzeTestSourcesRequest, analyzer: AnalyzerSetup
) -> AnalyzedTestSources:
    input_digest = await Get(Digest, MergeDigests([request.digest, analyzer.digest]))

    result = await Get(
        ProcessResult,
        Process(
            argv=(analyzer.path, *request.paths),
            input_digest=input_digest,
            description="Analyze Go test sources.",
        ),
    )

    metadata = json.loads(result.stdout.decode("utf-8"))
    return AnalyzedTestSources.from_json_dict(metadata)


def rules():
    return collect_rules()
