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
    CreateDigest,
    Digest,
    DigestContents,
    DigestEntries,
    DigestSubset,
    FileEntry,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.util.strutil import strip_v2_chroot_path


@dataclass(frozen=True)
class DownloadedExternalModules:
    """All downloaded modules, along with the input `go.mod` and `go.sum`."""

    digest: Digest


@dataclass(frozen=True)
class DownloadExternalModulesRequest:
    """Download all modules from the `go.mod`.

    The `go.mod` and `go.sum` must already be up-to-date.
    """

    go_mod_stripped_digest: Digest


@rule
async def download_external_modules(
    request: DownloadExternalModulesRequest,
) -> DownloadedExternalModules:
    download_result = await Get(
        ProcessResult,
        GoSdkProcess(
            command=("mod", "download", "-json", "all"),
            input_digest=request.go_mod_stripped_digest,
            # TODO: make this more descriptive: point to the actual `go_mod` target or path.
            description="Download all external Go modules",
            output_files=("go.mod", "go.sum"),
            output_directories=("gopath",),
        ),
    )

    # Check that the root `go.mod` and `go.sum` did not change.
    result_go_mod_digest = await Get(
        Digest, DigestSubset(download_result.output_digest, PathGlobs(["go.mod", "go.sum"]))
    )
    if result_go_mod_digest != request.go_mod_stripped_digest:
        # TODO: make this a more informative error.
        contents = await Get(DigestContents, Digest, result_go_mod_digest)

        raise Exception(
            "`go.mod` and/or `go.sum` changed! Please run `go mod tidy`.\n\n"
            f"{contents[0].content.decode()}\n\n"
            f"{contents[1].content.decode()}\n\n"
        )

    # TODO: strip `gopath` and other paths?
    # TODO: stop including irrelevant files like the `.zip` files.

    download_snapshot = await Get(Snapshot, Digest, download_result.output_digest)
    all_downloaded_files = set(download_snapshot.files)

    # To analyze each module via `go list`, we need a `go.mod` in each module's directory. If the
    # module does not natively use Go modules, then Go will generate a `go.mod` for us, but we
    # need to relocate the file to the correct location.
    module_dirs_with_go_mod = []
    generated_go_mods_to_module_dirs = {}
    for module_metadata in ijson.items(download_result.stdout, "", multiple_values=True):
        download_dir = strip_v2_chroot_path(module_metadata["Dir"])
        if f"{download_dir}/go.mod" in all_downloaded_files:
            module_dirs_with_go_mod.append(download_dir)
        else:
            generated_go_mod = strip_v2_chroot_path(module_metadata["GoMod"])
            generated_go_mods_to_module_dirs[generated_go_mod] = download_dir

    digest_entries = await Get(DigestEntries, Digest, download_result.output_digest)
    go_mod_requests = []
    for entry in digest_entries:
        if isinstance(entry, FileEntry) and entry.path in generated_go_mods_to_module_dirs:
            module_dir = generated_go_mods_to_module_dirs[entry.path]
            go_mod_requests.append(FileEntry(os.path.join(module_dir, "go.mod"), entry.file_digest))
    generated_go_mod_digest = await Get(Digest, CreateDigest(go_mod_requests))

    result_digest = await Get(
        Digest, MergeDigests([download_result.output_digest, generated_go_mod_digest])
    )
    return DownloadedExternalModules(result_digest)


@dataclass(frozen=True)
class DownloadExternalModuleRequest:
    path: str
    version: str
    go_sum_digest: Digest = EMPTY_DIGEST


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
class ExternalModulePkgImportPathsRequest:
    """Request the import paths for all packages belonging to an external Go module.

    The `go_sum_digest` must have a `go.sum` file that includes the module.
    """

    module_path: str
    version: str
    go_sum_digest: Digest


class ExternalModulePkgImportPaths(DeduplicatedCollection[str]):
    """The import paths for all packages belonging to an external Go module."""

    sort_input = True


@rule
async def compute_package_import_paths_from_external_module(
    request: ExternalModulePkgImportPathsRequest,
) -> ExternalModulePkgImportPaths:
    downloaded_module = await Get(
        DownloadedExternalModule,
        DownloadExternalModuleRequest(request.module_path, request.version, request.go_sum_digest),
    )
    json_result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=downloaded_module.digest,
            # "-find" skips determining dependencies and imports for each package.
            command=("list", "-find", "-json", "./..."),
            description=(
                "Determine import paths in Go external module "
                f"{request.module_path}@{request.version}"
            ),
        ),
    )
    return ExternalModulePkgImportPaths(
        metadata["ImportPath"]
        for metadata in ijson.items(json_result.stdout, "", multiple_values=True)
    )


def rules():
    return collect_rules()
