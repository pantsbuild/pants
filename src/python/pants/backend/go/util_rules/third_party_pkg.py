# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Tuple

import ijson

from pants.backend.go.util_rules.sdk import GoSdkProcess
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

# -----------------------------------------------------------------------------------------------
# Download modules
# -----------------------------------------------------------------------------------------------


class _AllDownloadedModules(FrozenDict[Tuple[str, str], Digest]):
    """A mapping of each downloaded (module, version) to its digest.

    Each digest is stripped of the `gopath` prefix and also guaranteed to have a `go.mod` and
    `go.sum` for the particular module. This means that you can operate on the module (e.g. `go
    list`) directly, without needing to set the working_dir etc.
    """


@dataclass(frozen=True)
class _AllDownloadedModulesRequest:
    """Download all modules from the `go.mod`.

    The `go.mod` and `go.sum` must already be up-to-date.
    """

    go_mod_stripped_digest: Digest


@dataclass(frozen=True)
class _DownloadedModule:
    """A downloaded module's directory.

    The digest is stripped of the `gopath` prefix and also guaranteed to have a `go.mod` and
    `go.sum` for the particular module. This means that you can operate on the module (e.g. `go
    list`) directly, without needing to set the working_dir etc.
    """

    digest: Digest


@dataclass(frozen=True)
class _DownloadedModuleRequest(EngineAwareParameter):
    module_path: str
    version: str
    go_mod_stripped_digest: Digest

    def debug_hint(self) -> str:
        return f"{self.module_path}@{self.version}"


@rule
async def download_third_party_modules(
    request: _AllDownloadedModulesRequest,
) -> _AllDownloadedModules:
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
            description="Download all third-party Go modules",
            output_files=("go.mod", "go.sum"),
            output_directories=("gopath",),
            allow_downloads=True,
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
    return _AllDownloadedModules(module_paths_and_versions_to_digests)


@rule
async def extract_module_from_downloaded_modules(
    request: _DownloadedModuleRequest,
) -> _DownloadedModule:
    all_modules = await Get(
        _AllDownloadedModules, _AllDownloadedModulesRequest(request.go_mod_stripped_digest)
    )
    digest = all_modules.get((request.module_path, request.version))
    if digest is None:
        raise AssertionError(
            f"The module {request.module_path}@{request.version} was not downloaded. This should "
            "not happen: please open an issue at "
            "https://github.com/pantsbuild/pants/issues/new/choose with this error message.\n\n"
            f"{all_modules}"
        )
    return _DownloadedModule(digest)


# -----------------------------------------------------------------------------------------------
# Determine package info
# -----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ThirdPartyPkgInfo:
    """All the info needed to build a third-party package.

    The digest is stripped of the `gopath` prefix.
    """

    import_path: str
    module_path: str
    version: str

    digest: Digest

    # Note that we don't care about test-related metadata like `TestImports`, as we'll never run
    # tests directly on a third-party package.
    imports: tuple[str, ...]
    go_files: tuple[str, ...]
    s_files: tuple[str, ...]

    unsupported_sources_error: NotImplementedError | None = None


@dataclass(frozen=True)
class ThirdPartyPkgInfoRequest(EngineAwareParameter):
    """Request the info and digest needed to build a third-party package.

    The package's module must be included in the input `go.mod`/`go.sum`.
    """

    import_path: str
    module_path: str
    version: str
    go_mod_stripped_digest: Digest

    def debug_hint(self) -> str:
        return self.import_path


class ThirdPartyModuleInfo(FrozenDict[str, ThirdPartyPkgInfo]):
    """A mapping of the import path for each package in the module to its
    `ThirdPartyPackageInfo`."""


@dataclass(frozen=True)
class ThirdPartyModuleInfoRequest(EngineAwareParameter):
    """Request info for every package contained in a third-party module.

    The module must be included in the input `go.mod`/`go.sum`.
    """

    module_path: str
    version: str
    go_mod_stripped_digest: Digest

    def debug_hint(self) -> str:
        return f"{self.module_path}@{self.version}"


@rule
async def compute_third_party_module_metadata(
    request: ThirdPartyModuleInfoRequest,
) -> ThirdPartyModuleInfo:
    downloaded_module = await Get(
        _DownloadedModule,
        _DownloadedModuleRequest(
            request.module_path, request.version, request.go_mod_stripped_digest
        ),
    )
    json_result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=downloaded_module.digest,
            command=("list", "-mod=readonly", "-json", "./..."),
            description=(
                "Determine metadata for Go third-party module "
                f"{request.module_path}@{request.version}"
            ),
        ),
    )

    # Some modules don't have any Go code in them, meaning they have no packages.
    if not json_result.stdout:
        return ThirdPartyModuleInfo()

    import_path_to_info = {}
    for metadata in ijson.items(json_result.stdout, "", multiple_values=True):
        import_path = metadata["ImportPath"]
        pkg_info = ThirdPartyPkgInfo(
            import_path=import_path,
            module_path=request.module_path,
            version=request.version,
            digest=downloaded_module.digest,
            imports=tuple(metadata.get("Imports", ())),
            go_files=tuple(metadata.get("GoFiles", ())),
            s_files=tuple(metadata.get("SFiles", ())),
            unsupported_sources_error=maybe_create_error_for_invalid_sources(
                metadata, import_path, request.module_path, request.version
            ),
        )
        import_path_to_info[import_path] = pkg_info
    return ThirdPartyModuleInfo(import_path_to_info)


@rule
async def extract_package_info_from_module_info(
    request: ThirdPartyPkgInfoRequest,
) -> ThirdPartyPkgInfo:
    module_info = await Get(
        ThirdPartyModuleInfo,
        ThirdPartyModuleInfoRequest(
            request.module_path, request.version, request.go_mod_stripped_digest
        ),
    )
    pkg_info = module_info.get(request.import_path)
    if pkg_info is None:
        raise AssertionError(
            f"The package {request.import_path} does not belong to the module "
            f"{request.module_path}@{request.version}. This should not happen: please open an "
            "issue at https://github.com/pantsbuild/pants/issues/new/choose with this error "
            "message.\n\n"
            f"{module_info}"
        )

    # We error if trying to _use_ a package with unsupported sources (vs. only generating the
    # target definition).
    if pkg_info.unsupported_sources_error:
        raise pkg_info.unsupported_sources_error

    return pkg_info


def maybe_create_error_for_invalid_sources(
    go_list_json: dict, import_path: str, module_path: str, version: str
) -> NotImplementedError | None:
    for key in (
        "CgoFiles",
        "CompiledGoFiles",
        "CFiles",
        "CXXFiles",
        "MFiles",
        "HFiles",
        "FFiles",
        "SwigFiles",
        "SwigCXXFiles",
        "SysoFiles",
    ):
        if key in go_list_json:
            return NotImplementedError(
                f"The third-party package {import_path} includes `{key}`, which Pants does "
                "not yet support. Please open a feature request at "
                "https://github.com/pantsbuild/pants/issues/new/choose so that we know to "
                "prioritize adding support. Please include this metadata:\n\n"
                f"package: {import_path}\n"
                f"module: {module_path}\n"
                f"version: {version}"
            )
    return None


def rules():
    return collect_rules()
