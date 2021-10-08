# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from pants.backend.go.target_types import (
    GoFirstPartyPackageSourcesField,
    GoFirstPartyPackageSubpathField,
)
from pants.backend.go.util_rules.go_mod import (
    GoModInfo,
    GoModInfoRequest,
    OwningGoMod,
    OwningGoModRequest,
)
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import Digest, MergeDigests
from pants.engine.process import ProcessResult
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

    imports: tuple[str, ...]
    test_imports: tuple[str, ...]
    xtest_imports: tuple[str, ...]

    go_files: tuple[str, ...]
    test_files: tuple[str, ...]
    xtest_files: tuple[str, ...]

    s_files: tuple[str, ...]


@dataclass(frozen=True)
class FirstPartyPkgInfoRequest(EngineAwareParameter):
    address: Address

    def debug_hint(self) -> str:
        return self.address.spec


@rule
async def compute_first_party_package_info(
    request: FirstPartyPkgInfoRequest,
) -> FirstPartyPkgInfo:
    wrapped_target, owning_go_mod = await MultiGet(
        Get(WrappedTarget, Address, request.address),
        Get(OwningGoMod, OwningGoModRequest(request.address)),
    )
    target = wrapped_target.target
    subpath = target[GoFirstPartyPackageSubpathField].value

    go_mod_info, pkg_sources = await MultiGet(
        Get(GoModInfo, GoModInfoRequest(owning_go_mod.address)),
        Get(HydratedSources, HydrateSourcesRequest(target[GoFirstPartyPackageSourcesField])),
    )
    input_digest = await Get(
        Digest, MergeDigests([pkg_sources.snapshot.digest, go_mod_info.digest])
    )

    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=input_digest,
            command=("list", "-json", f"./{subpath}"),
            description=f"Determine metadata for {target.address}",
            working_dir=owning_go_mod.address.spec_path,
        ),
    )
    metadata = json.loads(result.stdout)
    return FirstPartyPkgInfo(
        digest=pkg_sources.snapshot.digest,
        imports=tuple(metadata.get("Imports", [])),
        test_imports=tuple(metadata.get("TestImports", [])),
        xtest_imports=tuple(metadata.get("XTestImports", [])),
        go_files=tuple(metadata.get("GoFiles", [])),
        test_files=tuple(metadata.get("TestGoFiles", [])),
        xtest_files=tuple(metadata.get("XTestGoFiles", [])),
        s_files=tuple(metadata.get("SFiles", [])),
    )


def rules():
    return collect_rules()
