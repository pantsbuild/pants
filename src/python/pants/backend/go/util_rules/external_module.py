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
)
from pants.backend.go.util_rules.go_pkg import ResolvedGoPackage
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.build_graph.address import Address
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    DigestSubset,
    FileContent,
    GlobExpansionConjunction,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import WrappedTarget
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet


@dataclass(frozen=True)
class DownloadExternalModuleRequest:
    path: str
    version: str


@dataclass(frozen=True)
class DownloadedExternalModule:
    path: str
    version: str
    digest: Digest
    sum: str
    go_mod_sum: str

    def to_go_sum_lines(self):
        return f"{self.path} {self.version} {self.sum}\n{self.path} {self.version}/go.mod {self.go_mod_sum}\n"


@rule
async def download_external_module(
    request: DownloadExternalModuleRequest,
) -> DownloadedExternalModule:
    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=EMPTY_DIGEST,
            command=("mod", "download", "-json", f"{request.path}@{request.version}"),
            description=f"Download external Go module at {request.path}@{request.version}.",
            output_directories=("gopath",),
        ),
    )

    # Decode the module metadata.
    metadata = json.loads(result.stdout)

    # Find the path within the digest where the source was downloaded. The path will have a sandbox-specific
    # prefix that we need to strip down to the `gopath` path component.
    absolute_source_path = metadata["Dir"]
    gopath_index = absolute_source_path.index("gopath/")
    source_path = absolute_source_path[gopath_index:]

    source_digest = await Get(
        Digest,
        DigestSubset(
            result.output_digest,
            PathGlobs(
                [f"{source_path}/**"],
                glob_match_error_behavior=GlobMatchErrorBehavior.error,
                description_of_origin=f"the DownloadExternalModuleRequest for {request.path}@{request.version}",
            ),
        ),
    )

    source_snapshot_stripped = await Get(Snapshot, RemovePrefix(source_digest, source_path))
    if "go.mod" not in source_snapshot_stripped.files:
        # There was no go.mod in the downloaded source. Use the generated go.mod from the go tooling which
        # was returned in the module metadata.
        go_mod_absolute_path = metadata.get("GoMod")
        if not go_mod_absolute_path:
            raise ValueError(
                f"No go.mod was provided in download of Go external module {request.path}@{request.version}, "
                "and the module metadata did not identify a generated go.mod file to use instead."
            )
        gopath_index = go_mod_absolute_path.index("gopath/")
        go_mod_path = go_mod_absolute_path[gopath_index:]
        go_mod_digest = await Get(
            Digest,
            DigestSubset(
                result.output_digest,
                PathGlobs(
                    [f"{go_mod_path}"],
                    glob_match_error_behavior=GlobMatchErrorBehavior.error,
                    description_of_origin=f"the DownloadExternalModuleRequest for {request.path}@{request.version}",
                ),
            ),
        )
        go_mod_digest_stripped = await Get(
            Digest, RemovePrefix(go_mod_digest, os.path.dirname(go_mod_path))
        )

        # There should now be one file in the digest. Create a digest where that file is named go.mod
        # and then merge it into the sources.
        contents = await Get(DigestContents, Digest, go_mod_digest_stripped)
        assert len(contents) == 1
        go_mod_only_digest = await Get(
            Digest,
            CreateDigest(
                [
                    FileContent(
                        path="go.mod",
                        content=contents[0].content,
                    )
                ]
            ),
        )
        source_digest_final = await Get(
            Digest, MergeDigests([go_mod_only_digest, source_snapshot_stripped.digest])
        )
    else:
        # If the module download has a go.mod, then just use the sources as is.
        source_digest_final = source_snapshot_stripped.digest

    return DownloadedExternalModule(
        path=request.path,
        version=request.version,
        digest=source_digest_final,
        sum=metadata["Sum"],
        go_mod_sum=metadata["GoModSum"],
    )


@dataclass(frozen=True)
class ResolveExternalGoPackageRequest:
    address: Address


@rule
async def resolve_external_go_package(
    request: ResolveExternalGoPackageRequest,
) -> ResolvedGoPackage:
    wrapped_target = await Get(WrappedTarget, Address, request.address)
    target = wrapped_target.target

    import_path = target[GoExternalPackageImportPathField].value
    module_path = target[GoExternalModulePathField].value
    module_version = target[GoExternalModuleVersionField].value

    module = await Get(
        DownloadedExternalModule,
        DownloadExternalModuleRequest(
            path=module_path,
            version=module_version,
        ),
    )

    assert import_path.startswith(module_path)
    subpath = import_path[len(module_path) :]

    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=module.digest,
            command=("list", "-json", f"./{subpath}"),
            description="Resolve _go_external_package metadata.",
        ),
    )

    metadata = json.loads(result.stdout)
    return ResolvedGoPackage.from_metadata(
        metadata,
        import_path=import_path,
        address=request.address,
        module_address=None,
        module_path=module_path,
        module_version=module_version,
    )


@dataclass(frozen=True)
class ResolveExternalGoModuleToPackagesRequest:
    path: str
    version: str
    go_sum_digest: Digest


@dataclass(frozen=True)
class ResolveExternalGoModuleToPackagesResult:
    # TODO: Consider using DeduplicatedCollection if this is the only field.
    packages: FrozenOrderedSet[ResolvedGoPackage]


@rule
async def resolve_external_module_to_go_packages(
    request: ResolveExternalGoModuleToPackagesRequest,
) -> ResolveExternalGoModuleToPackagesResult:
    module_path = request.path
    assert module_path
    module_version = request.version
    assert module_version

    downloaded_module = await Get(
        DownloadedExternalModule,
        DownloadExternalModuleRequest(path=module_path, version=module_version),
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

    go_sum_only_digest = await Get(
        Digest, DigestSubset(request.go_sum_digest, PathGlobs(["go.sum"]))
    )
    go_sum_prefixed_digest = await Get(Digest, AddPrefix(go_sum_only_digest, "__sources__"))
    right_digest_contents = await Get(DigestContents, Digest, go_sum_prefixed_digest)
    right_go_sum_contents = b""
    for fc in right_digest_contents:
        if fc.path == "__sources__/go.sum":
            right_go_sum_contents = fc.content
            break
    go_sum_contents = left_go_sum_contents + b"\n" + right_go_sum_contents
    go_sum_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    path="__sources__/go.sum",
                    content=go_sum_contents,
                )
            ]
        ),
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

    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=input_digest,
            command=("list", "-json", "./..."),
            working_dir="__sources__",
            description=f"Resolve packages in Go external module {module_path}@{module_version}",
        ),
    )

    packages: OrderedSet[ResolvedGoPackage] = OrderedSet()
    for metadata in ijson.items(result.stdout, "", multiple_values=True):
        package = ResolvedGoPackage.from_metadata(
            metadata, module_path=module_path, module_version=module_version
        )
        packages.add(package)

    return ResolveExternalGoModuleToPackagesResult(packages=FrozenOrderedSet(packages))


def rules():
    return collect_rules()
