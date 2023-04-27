# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import enum
import hashlib
import os
from dataclasses import dataclass
from pathlib import PurePath

import chevron

from pants.backend.go.util_rules.sdk import GoSdkProcess, GoSdkToolIDRequest, GoSdkToolIDResult
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.build_graph.address import Address
from pants.core.goals.test import CoverageData
from pants.engine.fs import CreateDigest, DigestSubset, FileContent, PathGlobs
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class GoCoverageData(CoverageData):
    coverage_digest: Digest
    import_path: str
    sources_digest: Digest
    sources_dir_path: str
    pkg_target_address: Address


class GoCoverMode(enum.Enum):
    SET = "set"
    COUNT = "count"
    ATOMIC = "atomic"


@dataclass(frozen=True)
class GoCoverageConfig:
    # How to count the code usage.
    cover_mode: GoCoverMode

    # Import path patterns for packages which should be instrumented for code coverage.
    import_path_include_patterns: tuple[str, ...] = ()


@dataclass(frozen=True)
class ApplyCodeCoverageRequest:
    """Apply code coverage to a package using `go tool cover`."""

    digest: Digest
    dir_path: str
    go_files: tuple[str, ...]
    cgo_files: tuple[str, ...]
    cover_mode: GoCoverMode
    import_path: str


@dataclass(frozen=True)
class FileCodeCoverageMetadata:
    """Metadata for code coverage applied to a single Go file."""

    file_id: str
    go_file: str
    cover_go_file: str
    cover_var: str


@dataclass(frozen=True)
class BuiltGoPackageCodeCoverageMetadata:
    import_path: str
    cover_file_metadatas: tuple[FileCodeCoverageMetadata, ...]
    sources_digest: Digest
    sources_dir_path: str


@dataclass(frozen=True)
class ApplyCodeCoverageResult:
    digest: Digest
    cover_file_metadatas: tuple[FileCodeCoverageMetadata, ...]
    go_files: tuple[str, ...]
    cgo_files: tuple[str, ...]


@dataclass(frozen=True)
class ApplyCodeCoverageToFileRequest:
    digest: Digest
    go_file: str
    cover_go_file: str
    mode: GoCoverMode
    cover_var: str


@dataclass(frozen=True)
class ApplyCodeCoverageToFileResult:
    digest: Digest
    cover_go_file: str


@rule
async def go_apply_code_coverage_to_file(
    request: ApplyCodeCoverageToFileRequest,
) -> ApplyCodeCoverageToFileResult:
    cover_tool_id = await Get(GoSdkToolIDResult, GoSdkToolIDRequest("cover"))

    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=request.digest,
            command=[
                "tool",
                "cover",
                "-mode",
                request.mode.value,
                "-var",
                request.cover_var,
                "-o",
                request.cover_go_file,
                request.go_file,
            ],
            description=f"Apply Go coverage to: {request.go_file}",
            output_files=(str(request.cover_go_file),),
            env={"__PANTS_GO_COVER_TOOL_ID": cover_tool_id.tool_id},
        ),
    )

    return ApplyCodeCoverageToFileResult(
        digest=result.output_digest,
        cover_go_file=request.cover_go_file,
    )


def _hash_string(s: str) -> str:
    h = hashlib.sha256(s.encode())
    return h.hexdigest()[:12]


def _is_test_file(s: str) -> bool:
    return s.endswith("_test.go")


@rule
async def go_apply_code_coverage(request: ApplyCodeCoverageRequest) -> ApplyCodeCoverageResult:
    # Setup metadata for each file to which code coverage will be applied by assigning the name of the exported
    # variable which holds coverage counters for each file.
    file_metadatas: list[FileCodeCoverageMetadata] = []
    output_go_files = []
    output_cgo_files = []
    import_path_hash = _hash_string(request.import_path)
    for i, go_file in enumerate(request.go_files + request.cgo_files):
        if _is_test_file(go_file):
            if i < len(request.go_files):
                output_go_files.append(go_file)
            else:
                output_cgo_files.append(go_file)
            continue

        p = PurePath(go_file)
        cover_go_file = str(p.with_name(f"{p.stem}.cover.go"))
        file_metadatas.append(
            FileCodeCoverageMetadata(
                file_id=f"{request.import_path}/{go_file}",
                go_file=go_file,
                cover_go_file=cover_go_file,
                cover_var=f"GoCover_{import_path_hash}_{i}",
            )
        )
        if i < len(request.go_files):
            output_go_files.append(cover_go_file)
        else:
            output_cgo_files.append(cover_go_file)

    subsetted_digests = await MultiGet(
        Get(
            Digest,
            DigestSubset(
                request.digest,
                PathGlobs(
                    [os.path.join(request.dir_path, file_metadata.go_file)],
                    glob_match_error_behavior=GlobMatchErrorBehavior.error,
                    description_of_origin="coverage",
                ),
            ),
        )
        for file_metadata in file_metadatas
    )

    # Apply code coverage codegen to each file that will be analyzed.
    cover_results = await MultiGet(
        Get(
            ApplyCodeCoverageToFileResult,
            ApplyCodeCoverageToFileRequest(
                digest=go_file_digest,
                go_file=os.path.join(request.dir_path, file_metadata.go_file),
                cover_go_file=os.path.join(request.dir_path, file_metadata.cover_go_file),
                mode=request.cover_mode,
                cover_var=file_metadata.cover_var,
            ),
        )
        for file_metadata, go_file_digest in zip(file_metadatas, subsetted_digests)
    )

    # Merge the coverage codegen back into the original digest so that non-covered and covered sources are in
    # the same digest.
    digest = await Get(Digest, MergeDigests([request.digest, *(r.digest for r in cover_results)]))

    return ApplyCodeCoverageResult(
        digest=digest,
        cover_file_metadatas=tuple(file_metadatas),
        go_files=tuple(output_go_files),
        cgo_files=tuple(output_cgo_files),
    )


@dataclass(frozen=True)
class GenerateCoverageSetupCodeRequest:
    packages: FrozenOrderedSet[BuiltGoPackageCodeCoverageMetadata]
    cover_mode: GoCoverMode


@dataclass(frozen=True)
class GenerateCoverageSetupCodeResult:
    PATH = "pants_cover_setup.go"
    digest: Digest


COVERAGE_SETUP_CODE = """\
package main

import (
    "testing"

{{#imports}}
    _cover{{i}} "{{import_path}}"
{{/imports}}
)

var (
    coverCounters = make(map[string][]uint32)
    coverBlocks = make(map[string][]testing.CoverBlock)
)

func coverRegisterFile(fileName string, counter []uint32, pos []uint32, numStmts []uint16) {
    if 3*len(counter) != len(pos) || len(counter) != len(numStmts) {
        panic("coverage: mismatched sizes")
    }
    if coverCounters[fileName] != nil {
        // Already registered.
        return
    }
    coverCounters[fileName] = counter
    block := make([]testing.CoverBlock, len(counter))
    for i := range counter {
        block[i] = testing.CoverBlock{
            Line0: pos[3*i+0],
            Col0: uint16(pos[3*i+2]),
            Line1: pos[3*i+1],
            Col1: uint16(pos[3*i+2]>>16),
            Stmts: numStmts[i],
        }
    }
    coverBlocks[fileName] = block
}

func init() {
{{#registrations}}
    coverRegisterFile("{{file_id}}", _cover{{i}}.{{cover_var}}.Count[:], _cover{{i}}.{{cover_var}}.Pos[:], _cover{{i}}.{{cover_var}}.NumStmt[:])
{{/registrations}}
}

func registerCover() {
    testing.RegisterCover(testing.Cover{
        Mode: "{{cover_mode}}",
        Counters: coverCounters,
        Blocks: coverBlocks,
        CoveredPackages: "",
    })
}
"""


@rule
async def generate_go_coverage_setup_code(
    request: GenerateCoverageSetupCodeRequest,
) -> GenerateCoverageSetupCodeResult:
    content = chevron.render(
        template=COVERAGE_SETUP_CODE,
        data={
            "imports": [
                {"i": i, "import_path": pkg.import_path} for i, pkg in enumerate(request.packages)
            ],
            "registrations": [
                {
                    "i": i,
                    "file_id": m.file_id,
                    "cover_var": m.cover_var,
                }
                for i, pkg in enumerate(request.packages)
                for m in pkg.cover_file_metadatas
            ],
            "cover_mode": request.cover_mode.value,
        },
    )

    digest = await Get(
        Digest, CreateDigest([FileContent(GenerateCoverageSetupCodeResult.PATH, content.encode())])
    )
    return GenerateCoverageSetupCodeResult(digest=digest)


def rules():
    return collect_rules()
