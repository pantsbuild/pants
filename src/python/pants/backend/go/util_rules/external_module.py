# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
from dataclasses import dataclass

import ijson

from pants.backend.go.target_types import (
    GoExternalModulePathField,
    GoExternalModuleVersionField,
    GoExternalPackageImportPathField,
    GoExternalPackageTarget,
)
from pants.backend.go.util_rules.go_pkg import ResolvedGoPackage
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.collection import DeduplicatedCollection
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    DigestEntries,
    DigestSubset,
    FileContent,
    FileEntry,
    GlobExpansionConjunction,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.util.strutil import strip_v2_chroot_path


@dataclass(frozen=True)
class DownloadExternalModuleRequest:
    path: str
    version: str


@dataclass(frozen=True)
class DownloadedExternalModule:
    path: str
    version: str
    digest: Digest


@rule
async def download_external_module(
    request: DownloadExternalModuleRequest,
) -> DownloadedExternalModule:
    download_result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=EMPTY_DIGEST,
            command=("mod", "download", "-json", f"{request.path}@{request.version}"),
            description=f"Download external Go module at {request.path}@{request.version}.",
            output_directories=("gopath",),
        ),
    )

    metadata = json.loads(download_result.stdout)

    _download_path = strip_v2_chroot_path(metadata["Dir"])
    _download_digest_unstripped = await Get(
        Digest,
        DigestSubset(
            download_result.output_digest,
            PathGlobs(
                [f"{_download_path}/**"],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=(
                    f"the DownloadExternalModuleRequest for {request.path}@{request.version}"
                ),
            ),
        ),
    )
    download_snapshot = await Get(
        Snapshot, RemovePrefix(_download_digest_unstripped, _download_path)
    )

    if "go.mod" in download_snapshot.files:
        return DownloadedExternalModule(
            path=request.path,
            version=request.version,
            digest=download_snapshot.digest,
        )

    # Else, there was no go.mod in the downloaded source. Use the generated go.mod from the Go
    # tooling.
    if "GoMod" not in metadata:
        raise AssertionError(
            "No go.mod was provided in download of Go external module "
            f"{request.path}@{request.version}, and the module metadata did not identify a "
            "generated go.mod file to use instead.\n\n"
            "Please open a bug at https://github.com/pantsbuild/pants/issues/new/choose with the "
            "above information."
        )

    _go_mod_path = strip_v2_chroot_path(metadata["GoMod"])
    _go_mod_digest_unstripped = await Get(
        Digest,
        DigestSubset(
            download_result.output_digest,
            PathGlobs(
                [f"{_go_mod_path}"],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=(
                    f"the DownloadExternalModuleRequest for {request.path}@{request.version}"
                ),
            ),
        ),
    )
    original_go_mod_digest = await Get(
        Digest, RemovePrefix(_go_mod_digest_unstripped, os.path.dirname(_go_mod_path))
    )

    # Rename the `.mod` file to the standard `go.mod` name.
    entries = await Get(DigestEntries, Digest, original_go_mod_digest)
    assert len(entries) == 1
    file_entry = entries[0]
    assert isinstance(file_entry, FileEntry)
    go_mod_digest = await Get(Digest, CreateDigest([FileEntry("go.mod", file_entry.file_digest)]))

    result_digest = await Get(Digest, MergeDigests([go_mod_digest, download_snapshot.digest]))
    return DownloadedExternalModule(
        path=request.path,
        version=request.version,
        digest=result_digest,
    )


@dataclass(frozen=True)
class ResolveExternalGoPackageRequest:
    tgt: GoExternalPackageTarget


@rule
async def resolve_external_go_package(
    request: ResolveExternalGoPackageRequest,
) -> ResolvedGoPackage:
    module_path = request.tgt[GoExternalModulePathField].value
    module_version = request.tgt[GoExternalModuleVersionField].value

    import_path = request.tgt[GoExternalPackageImportPathField].value
    assert import_path.startswith(module_path)
    subpath = import_path[len(module_path) :]

    downloaded_module = await Get(
        DownloadedExternalModule,
        DownloadExternalModuleRequest(module_path, module_version),
    )

    json_result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=downloaded_module.digest,
            command=("list", "-json", f"./{subpath}"),
            description="Resolve _go_external_package metadata.",
        ),
    )

    metadata = json.loads(json_result.stdout)
    return ResolvedGoPackage.from_metadata(
        metadata,
        import_path=import_path,
        address=request.tgt.address,
        module_address=None,
        module_path=module_path,
        module_version=module_version,
    )


@dataclass(frozen=True)
class PackagesFromExternalModuleRequest:
    module_path: str
    version: str
    go_sum_digest: Digest


class PackagesFromExternalModule(DeduplicatedCollection[ResolvedGoPackage]):
    pass


@rule
async def compute_packages_from_external_module(
    request: PackagesFromExternalModuleRequest,
) -> PackagesFromExternalModule:
    module_path = request.module_path
    module_version = request.version

    downloaded_module = await Get(
        DownloadedExternalModule,
        DownloadExternalModuleRequest(module_path, module_version),
    )
    sources_digest = await Get(Digest, AddPrefix(downloaded_module.digest, "__sources__"))

    # TODO: Super hacky merge of go.sum from both digests. We should really just pass in the fully-resolved
    # go.sum and use that, but this allows the go.sum from the downloaded module to have some effect. Not sure
    # if that is right call, but hackity hack!
    left_digest_contents = await Get(DigestContents, Digest, sources_digest)
    left_go_sum_contents = b""
    for fc in left_digest_contents:
        if fc.path == "__sources__/go.sum":
            left_go_sum_contents = fc.content
            break

    go_sum_prefixed_digest = await Get(Digest, AddPrefix(request.go_sum_digest, "__sources__"))
    right_digest_contents = await Get(DigestContents, Digest, go_sum_prefixed_digest)
    right_go_sum_contents = b""
    for fc in right_digest_contents:
        if fc.path == "__sources__/go.sum":
            right_go_sum_contents = fc.content
            break
    go_sum_contents = left_go_sum_contents + b"\n" + right_go_sum_contents
    go_sum_digest = await Get(
        Digest, CreateDigest([FileContent("__sources__/go.sum", go_sum_contents)])
    )

    sources_digest_no_go_sum = await Get(
        Digest,
        DigestSubset(
            sources_digest,
            PathGlobs(
                ["!__sources__/go.sum", "__sources__/**"],
                conjunction=GlobExpansionConjunction.all_match,
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin="FUNKY",
            ),
        ),
    )

    input_digest = await Get(Digest, MergeDigests([sources_digest_no_go_sum, go_sum_digest]))

    json_result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=input_digest,
            command=("list", "-json", "./..."),
            working_dir="__sources__",
            description=f"Resolve packages in Go external module {module_path}@{module_version}",
        ),
    )

    return PackagesFromExternalModule(
        ResolvedGoPackage.from_metadata(
            metadata, module_path=module_path, module_version=module_version
        )
        for metadata in ijson.items(json_result.stdout, "", multiple_values=True)
    )


def rules():
    return collect_rules()
