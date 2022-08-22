# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import enum
import hashlib
import os
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.go.util_rules.sdk import GoSdkProcess, GoSdkToolIDRequest, GoSdkToolIDResult
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
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


class GoCoverMode(enum.Enum):
    SET = "set"
    COUNT = "count"
    ATOMIC = "atomic"


@dataclass(frozen=True)
class GoCoverageConfig:
    cover_mode: GoCoverMode


@dataclass(frozen=True)
class ApplyCodeCoverageRequest:
    """Apply code coverage to a package using `go tool cover`."""

    digest: Digest
    dir_path: str
    go_files: tuple[str, ...]
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


@dataclass(frozen=True)
class ApplyCodeCoverageResult:
    digest: Digest
    cover_file_metadatas: tuple[FileCodeCoverageMetadata, ...]


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


@rule
async def go_apply_code_coverage(request: ApplyCodeCoverageRequest) -> ApplyCodeCoverageResult:
    # Code coverage is never applied to test files.
    go_files = [go_file for go_file in request.go_files if not go_file.endswith("_test.go")]

    subsetted_digests = await MultiGet(
        Get(
            Digest,
            DigestSubset(
                request.digest,
                PathGlobs(
                    [os.path.join(request.dir_path, go_file)],
                    glob_match_error_behavior=GlobMatchErrorBehavior.error,
                    description_of_origin="coverage",
                ),
            ),
        )
        for go_file in go_files
    )

    # Setup metadata for each file to which code coverage will be applied by assigning the name of the exported
    # variable which holds coverage counters for each file.
    import_path_hash = _hash_string(request.import_path)
    file_metadatas = []
    for i, go_file in enumerate(go_files):
        p = PurePath(go_file)
        file_metadatas.append(
            FileCodeCoverageMetadata(
                file_id=f"{request.import_path}/{go_file}",
                go_file=go_file,
                cover_go_file=str(p.with_name(f"{p.stem}.cover-{i}.go")),
                cover_var=f"GoCover_{import_path_hash}_{i}",
            )
        )

    cover_results = await MultiGet(
        Get(
            ApplyCodeCoverageToFileResult,
            ApplyCodeCoverageToFileRequest(
                digest=go_file_digest,
                go_file=os.path.join(request.dir_path, m.go_file),
                cover_go_file=os.path.join(request.dir_path, m.cover_go_file),
                mode=request.cover_mode,
                cover_var=m.cover_var,
            ),
        )
        for m, go_file_digest in zip(file_metadatas, subsetted_digests)
    )

    digest = await Get(Digest, MergeDigests([r.digest for r in cover_results]))
    return ApplyCodeCoverageResult(
        digest=digest,
        cover_file_metadatas=tuple(file_metadatas),
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

@IMPORTS@
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
@REGISTRATIONS@
}

func registerCover() {
    testing.RegisterCover(testing.Cover{
        Mode: "@COVER_MODE@",
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
    imports_partial = "".join(
        [f'    _cover{i} "{pkg.import_path}"\n' for i, pkg in enumerate(request.packages)]
    ).rstrip()

    registrations_partial = "".join(
        [
            f'    coverRegisterFile("{m.file_id}", _cover{i}.{m.cover_var}.Count[:], '
            f"_cover{i}.{m.cover_var}.Pos[:], _cover{i}.{m.cover_var}.NumStmt[:])\n"
            for i, pkg in enumerate(request.packages)
            for m in pkg.cover_file_metadatas
        ]
    ).rstrip()

    content = (
        COVERAGE_SETUP_CODE.replace("@IMPORTS@", imports_partial)
        .replace("@REGISTRATIONS@", registrations_partial)
        .replace("@COVER_MODE@", request.cover_mode.value)
    )

    digest = await Get(
        Digest, CreateDigest([FileContent(GenerateCoverageSetupCodeResult.PATH, content.encode())])
    )
    return GenerateCoverageSetupCodeResult(digest=digest)


def rules():
    return collect_rules()
