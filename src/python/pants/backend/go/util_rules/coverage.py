# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import enum
import hashlib
import os
from dataclasses import dataclass
from pathlib import PurePath

import chevron

from pants.backend.go.util_rules.goroot import GoRoot
from pants.backend.go.util_rules.sdk import GoSdkProcess, GoSdkToolIDRequest, compute_go_tool_id
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.build_graph.address import Address
from pants.core.goals.test import CoverageData
from pants.engine.fs import CreateDigest, DigestSubset, FileContent, PathGlobs
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import create_digest, digest_subset_to_digest, merge_digests
from pants.engine.process import fallible_to_exec_result_or_raise
from pants.engine.rules import collect_rules, implicitly, rule
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
    cover_tool_id = await compute_go_tool_id(GoSdkToolIDRequest("cover"))

    result = await fallible_to_exec_result_or_raise(
        **implicitly(
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
            )
        )
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

    subsetted_digests = await concurrently(
        digest_subset_to_digest(
            DigestSubset(
                request.digest,
                PathGlobs(
                    [os.path.join(request.dir_path, file_metadata.go_file)],
                    glob_match_error_behavior=GlobMatchErrorBehavior.error,
                    description_of_origin="coverage",
                ),
            )
        )
        for file_metadata in file_metadatas
    )

    # Apply code coverage codegen to each file that will be analyzed.
    cover_results = await concurrently(
        go_apply_code_coverage_to_file(
            ApplyCodeCoverageToFileRequest(
                digest=go_file_digest,
                go_file=os.path.join(request.dir_path, file_metadata.go_file),
                cover_go_file=os.path.join(request.dir_path, file_metadata.cover_go_file),
                mode=request.cover_mode,
                cover_var=file_metadata.cover_var,
            )
        )
        for file_metadata, go_file_digest in zip(file_metadatas, subsetted_digests)
    )

    # Merge the coverage codegen back into the original digest so that non-covered and covered sources are in
    # the same digest.
    digest = await merge_digests(MergeDigests([request.digest, *(r.digest for r in cover_results)]))

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


# The Go stdlib packages imported by the coverage setup code generated for Go v1.25+.
#
# `prepare_go_test_binary` must add these as direct dependencies of the synthetic main package:
# the package analyzer only ever sees `testmain.go` (that is the sole output of the
# `generate_testmain` process), so imports which appear only in `pants_cover_setup.go` would
# otherwise never make it into the `importcfg` for the main package.
COVERAGE_SETUP_TESTDEPS_IMPORTS: tuple[str, ...] = ("fmt", "io", "os", "sync/atomic")


# The import path `go tool cover -mode=atomic` injects into every covered package.
SYNC_ATOMIC_IMPORT_PATH = "sync/atomic"


def requires_sync_atomic_dependency(
    with_coverage: bool, coverage_config: GoCoverageConfig | None
) -> bool:
    """Whether a package instrumented for coverage needs `sync/atomic` in its `importcfg`.

    `go tool cover -mode=atomic` rewrites each covered statement to call
    `sync/atomic.AddUint32`, adding an import the package's own sources never declared. Pants
    builds each package's `importcfg` from its direct dependencies, so unless `sync/atomic` is
    added explicitly the package fails to compile with "could not import sync/atomic". Packages
    which happen to import `sync/atomic` already are unaffected, which is why this only breaks
    some of them.
    """
    return (
        with_coverage
        and coverage_config is not None
        and coverage_config.cover_mode == GoCoverMode.ATOMIC
    )


def registers_coverage_via_testdeps(goroot: GoRoot) -> bool:
    """Whether the coverage setup code must register coverage through `testing/internal/testdeps`.

    Pants instruments Go sources with the "legacy" coverage mechanism (`go tool cover -mode -var`),
    which stores counters in exported package-level variables. Those counters used to be handed to
    the `testing` package via `testing.RegisterCover`.

    Go v1.20 replaced that mechanism with the "coverage redesign", under which `RegisterCover` is
    ignored: `testing.CoverMode()` reads the state registered by `testing.MainStart` instead. Up to
    Go v1.24 Pants avoided the problem by building everything with
    `GOEXPERIMENT=nocoverageredesign` (see `sdk.py`), which restores the old implementation. Go
    v1.25 removed that experiment, and with it `RegisterCover`'s body, so on Go v1.25+ the counters
    have to be registered the way `cmd/go`'s own generated testmain does it - by pointing the
    `testing/internal/testdeps` hooks at our own profile writer.
    """
    return goroot.is_compatible_version("1.25")


COVERAGE_SETUP_CODE = """\
package main

import (
{{#use_testdeps}}
    "fmt"
    "io"
    "os"
    "sync/atomic"
{{/use_testdeps}}
    "testing"
{{#use_testdeps}}
    "testing/internal/testdeps"
{{/use_testdeps}}
{{#imports}}
    _cover{{i}} "{{import_path}}"
{{/imports}}
)

var (
    coverCounters = make(map[string][]uint32)
    coverBlocks = make(map[string][]testing.CoverBlock)
{{#use_testdeps}}
    // Registration order of `coverCounters`. Iteration order of a Go map is randomized, so the
    // coverage profile is written by walking this slice instead: `cover.out` ends up in a `Digest`
    // which is materialized to `dist/`, and unstable output would mean an unstable cache key.
    coverFileNames []string
{{/use_testdeps}}
)

func coverRegisterFile(fileName string, counter []uint32, pos []uint32, numStmts []uint16) {
    if 3*len(counter) != len(pos) || len(counter) != len(numStmts) {
        panic("coverage: mismatched sizes")
    }
    if coverCounters[fileName] != nil {
        // Already registered.
        return
    }
{{#use_testdeps}}
    coverFileNames = append(coverFileNames, fileName)
{{/use_testdeps}}
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
{{#use_testdeps}}

// coverSnapshot backs `testing.Coverage()`. It reports the fraction of covered basic blocks,
// matching what the `testing` package itself used to compute.
func coverSnapshot() float64 {
    var n, d int64
    for _, fileName := range coverFileNames {
        counters := coverCounters[fileName]
        for i := range counters {
            if atomic.LoadUint32(&counters[i]) > 0 {
                n++
            }
            d++
        }
    }
    if d == 0 {
        return 0
    }
    return float64(n) / float64(d)
}

// coverWriteProfile writes the coverage profile in the "textfmt" format understood by
// `go tool cover`. It is installed as `testdeps.CoverProcessTestDirFunc` and so is invoked by
// `testing.M.Run` once the tests have finished.
func coverWriteProfile(_ string, coverProfile string, coverMode string, coveredPackages string, w io.Writer, _ []string) (err error) {
    var f *os.File
    if coverProfile != "" {
        f, err = os.Create(coverProfile)
        if err != nil {
            return err
        }
        defer func() {
            if closeErr := f.Close(); err == nil {
                err = closeErr
            }
        }()
        if _, err = fmt.Fprintf(f, "mode: %s\\n", coverMode); err != nil {
            return err
        }
    }

    var active, total int64
    for _, fileName := range coverFileNames {
        counters := coverCounters[fileName]
        blocks := coverBlocks[fileName]
        for i := range counters {
            stmts := int64(blocks[i].Stmts)
            total += stmts
            count := atomic.LoadUint32(&counters[i]) // For -mode=atomic.
            if count > 0 {
                active += stmts
            }
            if f == nil {
                continue
            }
            if _, err = fmt.Fprintf(f, "%s:%d.%d,%d.%d %d %d\\n", fileName,
                blocks[i].Line0, blocks[i].Col0,
                blocks[i].Line1, blocks[i].Col1,
                stmts,
                count); err != nil {
                return err
            }
        }
    }

    if total == 0 {
        fmt.Fprintln(w, "coverage: [no statements]")
        return nil
    }
    fmt.Fprintf(w, "coverage: %.1f%% of statements%s\\n", 100*float64(active)/float64(total), coveredPackages)
    return nil
}
{{/use_testdeps}}

func registerCover() {
{{#use_testdeps}}
    testdeps.CoverMode = "{{cover_mode}}"
    testdeps.CoverSnapshotFunc = coverSnapshot
    testdeps.CoverProcessTestDirFunc = coverWriteProfile
    testdeps.CoverMarkProfileEmittedFunc = func(bool) {}
{{/use_testdeps}}
{{^use_testdeps}}
    testing.RegisterCover(testing.Cover{
        Mode: "{{cover_mode}}",
        Counters: coverCounters,
        Blocks: coverBlocks,
        CoveredPackages: "",
    })
{{/use_testdeps}}
}
"""


@rule
async def generate_go_coverage_setup_code(
    request: GenerateCoverageSetupCodeRequest,
    goroot: GoRoot,
) -> GenerateCoverageSetupCodeResult:
    # Sort the packages, and the per-file registrations within them, so that the generated code (and
    # thus the order in which the coverage profile is written) does not depend on the order in which
    # the packages happened to be built.
    packages = sorted(request.packages, key=lambda pkg: pkg.import_path)
    registrations = sorted(
        (
            (package_index, file_metadata)
            for package_index, pkg in enumerate(packages)
            for file_metadata in pkg.cover_file_metadatas
        ),
        key=lambda registration: registration[1].file_id,
    )
    content = chevron.render(
        template=COVERAGE_SETUP_CODE,
        data={
            "use_testdeps": registers_coverage_via_testdeps(goroot),
            "imports": [{"i": i, "import_path": pkg.import_path} for i, pkg in enumerate(packages)],
            "registrations": [
                {
                    "i": package_index,
                    "file_id": file_metadata.file_id,
                    "cover_var": file_metadata.cover_var,
                }
                for package_index, file_metadata in registrations
            ],
            "cover_mode": request.cover_mode.value,
        },
    )

    digest = await create_digest(
        CreateDigest([FileContent(GenerateCoverageSetupCodeResult.PATH, content.encode())])
    )
    return GenerateCoverageSetupCodeResult(digest=digest)


def rules():
    return collect_rules()
