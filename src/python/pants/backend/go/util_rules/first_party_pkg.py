# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from pants.backend.go.target_types import (
    GoFirstPartyPackageSourcesField,
    GoFirstPartyPackageSubpathField,
    GoImportPathField,
)
from pants.backend.go.util_rules.go_mod import GoModInfo, GoModInfoRequest
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import HydratedSources, HydrateSourcesRequest, WrappedTarget

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FirstPartyPkgInfo:
    """All the info and digest needed to build a first-party Go package.

    The digest does not strip its source files. You must set `working_dir` appropriately to use the
    `go_first_party_package` target's `subpath` field.
    """

    digest: Digest
    subpath: str

    import_path: str

    imports: tuple[str, ...]
    test_imports: tuple[str, ...]
    xtest_imports: tuple[str, ...]

    go_files: tuple[str, ...]
    test_files: tuple[str, ...]
    xtest_files: tuple[str, ...]

    s_files: tuple[str, ...]


@dataclass(frozen=True)
class FallibleFirstPartyPkgInfo:
    """Info needed to build a first-party Go package, but fallible if `go list` failed."""

    info: FirstPartyPkgInfo | None
    import_path: str
    exit_code: int = 0
    stderr: str | None = None


@dataclass(frozen=True)
class FirstPartyPkgInfoRequest(EngineAwareParameter):
    address: Address

    def debug_hint(self) -> str:
        return self.address.spec


@rule
async def compute_first_party_package_info(
    request: FirstPartyPkgInfoRequest,
) -> FallibleFirstPartyPkgInfo:
    go_mod_address = request.address.maybe_convert_to_target_generator()
    wrapped_target, go_mod_info = await MultiGet(
        Get(WrappedTarget, Address, request.address),
        Get(GoModInfo, GoModInfoRequest(go_mod_address)),
    )
    target = wrapped_target.target
    import_path = target[GoImportPathField].value
    subpath = target[GoFirstPartyPackageSubpathField].value

    pkg_sources = await Get(
        HydratedSources, HydrateSourcesRequest(target[GoFirstPartyPackageSourcesField])
    )
    input_digest = await Get(
        Digest, MergeDigests([pkg_sources.snapshot.digest, go_mod_info.digest])
    )

    result = await Get(
        FallibleProcessResult,
        GoSdkProcess(
            input_digest=input_digest,
            command=("list", "-json", f"./{subpath}"),
            description=f"Determine metadata for {request.address}",
            working_dir=request.address.spec_path,
        ),
    )
    if result.exit_code != 0:
        return FallibleFirstPartyPkgInfo(
            info=None,
            import_path=import_path,
            exit_code=result.exit_code,
            stderr=result.stderr.decode("utf-8"),
        )

    metadata = json.loads(result.stdout)

    if "CgoFiles" in metadata:
        raise NotImplementedError(
            f"The first-party package {request.address} includes `CgoFiles`, which Pants does "
            "not yet support. Please open a feature request at "
            "https://github.com/pantsbuild/pants/issues/new/choose so that we know to "
            "prioritize adding support."
        )

    info = FirstPartyPkgInfo(
        digest=pkg_sources.snapshot.digest,
        subpath=os.path.join(target.address.spec_path, subpath),
        import_path=import_path,
        imports=tuple(metadata.get("Imports", [])),
        test_imports=tuple(metadata.get("TestImports", [])),
        xtest_imports=tuple(metadata.get("XTestImports", [])),
        go_files=tuple(metadata.get("GoFiles", [])),
        test_files=tuple(metadata.get("TestGoFiles", [])),
        xtest_files=tuple(metadata.get("XTestGoFiles", [])),
        s_files=tuple(metadata.get("SFiles", [])),
    )
    return FallibleFirstPartyPkgInfo(info, import_path)


def rules():
    return collect_rules()
