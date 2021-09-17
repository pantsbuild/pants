# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
from dataclasses import dataclass

from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.fs import (
    EMPTY_DIGEST,
    CreateDigest,
    Digest,
    DigestContents,
    DigestSubset,
    FileContent,
    MergeDigests,
    PathGlobs,
    RemovePrefix,
    Snapshot,
)
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule


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


def rules():
    return collect_rules()
