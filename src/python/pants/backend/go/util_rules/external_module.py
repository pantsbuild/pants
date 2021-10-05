# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
from dataclasses import dataclass
from typing import Tuple

import ijson

from pants.backend.go.target_types import (
    GoExternalModulePathField,
    GoExternalModuleVersionField,
    GoExternalPackageImportPathField,
    GoExternalPackageTarget,
)
from pants.backend.go.util_rules.go_pkg import ResolvedGoPackage
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.engine.collection import DeduplicatedCollection
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    DigestEntries,
    DigestSubset,
    FileEntry,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.util.frozendict import FrozenDict
from pants.util.strutil import strip_v2_chroot_path


class AllDownloadedModules(FrozenDict[Tuple[str, str], Digest]):
    """A mapping of each downloaded (module, version) to its digest.

    Each digest is stripped of the `gopath` prefix and also guaranteed to have a `go.mod` and
    `go.sum` for the particular module. This means that you can operate on the module (e.g. `go
    list`) directly, without needing to set the working_dir etc.
    """


@dataclass(frozen=True)
class AllDownloadedModulesRequest:
    """Download all modules from the `go.mod`.

    The `go.mod` and `go.sum` must already be up-to-date.
    """

    go_mod_stripped_digest: Digest


@rule
async def download_external_modules(
    request: AllDownloadedModulesRequest,
) -> AllDownloadedModules:
    # TODO: Clean this up.
    input_digest_entries = await Get(DigestEntries, Digest, request.go_mod_stripped_digest)
    assert len(input_digest_entries) == 2
    go_sum_file_digest = next(
        file_entry.file_digest
        for file_entry in input_digest_entries
        if isinstance(file_entry, FileEntry) and file_entry.path == "go.sum"
    )

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

    download_snapshot = await Get(Snapshot, Digest, download_result.output_digest)
    all_downloaded_files = set(download_snapshot.files)

    # To analyze each module via `go list`, we need its own `go.mod`, along with a `go.sum` that
    # includes it and its deps:
    #
    #  * If the module does not already have `go.mod`, Go will have generated it.
    #  * Our `go.sum` should be a superset of each module, so we can simply use that. Note that we
    #    eagerly error if the `go.sum` changed during the download, so we can be confident
    #    that the on-disk `go.sum` is comprehensive. TODO(#13093): subset this somehow?
    module_paths_and_versions_to_dirs = {}
    missing_go_sums = []
    generated_go_mods_to_module_dirs = {}
    for module_metadata in ijson.items(download_result.stdout, "", multiple_values=True):
        download_dir = strip_v2_chroot_path(module_metadata["Dir"])
        module_paths_and_versions_to_dirs[
            (module_metadata["Path"], module_metadata["Version"])
        ] = download_dir
        _go_sum = os.path.join(download_dir, "go.sum")
        if _go_sum not in all_downloaded_files:
            missing_go_sums.append(FileEntry(_go_sum, go_sum_file_digest))
        if os.path.join(download_dir, "go.mod") not in all_downloaded_files:
            generated_go_mod = strip_v2_chroot_path(module_metadata["GoMod"])
            generated_go_mods_to_module_dirs[generated_go_mod] = download_dir

    digest_entries = await Get(DigestEntries, Digest, download_result.output_digest)
    go_mod_requests = []
    for entry in digest_entries:
        if isinstance(entry, FileEntry) and entry.path in generated_go_mods_to_module_dirs:
            module_dir = generated_go_mods_to_module_dirs[entry.path]
            go_mod_requests.append(FileEntry(os.path.join(module_dir, "go.mod"), entry.file_digest))

    generated_digest = await Get(Digest, CreateDigest([*missing_go_sums, *go_mod_requests]))
    full_digest = await Get(Digest, MergeDigests([download_result.output_digest, generated_digest]))

    subsets = await MultiGet(
        Get(
            Digest,
            DigestSubset(
                full_digest,
                PathGlobs(
                    [f"{module_dir}/**"],
                    glob_match_error_behavior=GlobMatchErrorBehavior.error,
                    description_of_origin=f"downloading {module}@{version}",
                ),
            ),
        )
        for (module, version), module_dir in module_paths_and_versions_to_dirs.items()
    )
    stripped_subsets = await MultiGet(
        Get(Digest, RemovePrefix(digest, module_dir))
        for digest, module_dir in zip(subsets, module_paths_and_versions_to_dirs.values())
    )
    module_paths_and_versions_to_digests = {
        mod_and_version: digest
        for mod_and_version, digest in zip(
            module_paths_and_versions_to_dirs.keys(), stripped_subsets
        )
    }
    return AllDownloadedModules(module_paths_and_versions_to_digests)


@dataclass(frozen=True)
class DownloadedModule:
    """A downloaded module's directory.

    The digest is stripped of the `gopath` prefix and also guaranteed to have a `go.mod` and
    `go.sum` for the particular module. This means that you can operate on the module (e.g. `go
    list`) directly, without needing to set the working_dir etc.
    """

    digest: Digest


@dataclass(frozen=True)
class DownloadedModuleRequest:
    module_path: str
    version: str
    go_mod_stripped_digest: Digest


@rule
async def extract_module_from_downloaded_modules(
    request: DownloadedModuleRequest,
) -> DownloadedModule:
    all_modules = await Get(
        AllDownloadedModules, AllDownloadedModulesRequest(request.go_mod_stripped_digest)
    )
    digest = all_modules.get((request.module_path, request.version))
    if digest is None:
        raise AssertionError(
            f"The module {request.module_path}@{request.version} was not downloaded. Unless "
            "you explicitly created an `_go_external_package`, this should not happen."
            "Please open an issue at https://github.com/pantsbuild/pants/issues/new/choose with "
            "this error message."
        )
    return DownloadedModule(digest)


@dataclass(frozen=True)
class ResolveExternalGoPackageRequest(EngineAwareParameter):
    tgt: GoExternalPackageTarget
    go_mod_stripped_digest: Digest

    def debug_hint(self) -> str:
        return self.tgt[GoExternalPackageImportPathField].value


@rule
async def compute_external_go_package_info(
    request: ResolveExternalGoPackageRequest,
) -> ResolvedGoPackage:
    module_path = request.tgt[GoExternalModulePathField].value
    module_version = request.tgt[GoExternalModuleVersionField].value

    downloaded_module = await Get(
        DownloadedModule,
        DownloadedModuleRequest(module_path, module_version, request.go_mod_stripped_digest),
    )

    import_path = request.tgt[GoExternalPackageImportPathField].value
    assert import_path.startswith(module_path)
    subpath = import_path[len(module_path) :]

    json_result = await Get(
        ProcessResult,
        GoSdkProcess(
            command=("list", "-mod=readonly", "-json", f"./{subpath}"),
            env={"GOPROXY": "off"},
            input_digest=downloaded_module.digest,
            description=f"Determine metadata for Go external package {import_path}",
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

    The module must be included in the input `go.mod`/`go.sum`.
    """

    module_path: str
    version: str
    go_mod_stripped_digest: Digest


class ExternalModulePkgImportPaths(DeduplicatedCollection[str]):
    """The import paths for all packages belonging to an external Go module."""

    sort_input = True


@rule
async def compute_package_import_paths_from_external_module(
    request: ExternalModulePkgImportPathsRequest,
) -> ExternalModulePkgImportPaths:
    downloaded_module = await Get(
        DownloadedModule,
        DownloadedModuleRequest(
            request.module_path, request.version, request.go_mod_stripped_digest
        ),
    )
    json_result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=downloaded_module.digest,
            # "-find" skips determining dependencies and imports for each package.
            command=("list", "-find", "-mod=readonly", "-json", "./..."),
            env={"GOPROXY": "off"},
            description=(
                "Determine packages belonging to Go external module "
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
