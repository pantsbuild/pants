# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from pants.backend.go.target_types import GoModSourcesField
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.base.specs import AncestorGlobSpec, RawSpecs
from pants.build_graph.address import Address
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import Digest
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    InvalidTargetException,
    UnexpandedTargets,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.util.docutil import bin_name

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OwningGoModRequest(EngineAwareParameter):
    address: Address

    def debug_hint(self) -> str:
        return self.address.spec


@dataclass(frozen=True)
class OwningGoMod:
    address: Address


@rule
async def find_nearest_go_mod(request: OwningGoModRequest) -> OwningGoMod:
    # We don't expect `go_mod` targets to be generated, so we can use UnexpandedTargets.
    candidate_targets = await Get(
        UnexpandedTargets,
        RawSpecs(
            ancestor_globs=(AncestorGlobSpec(request.address.spec_path),),
            description_of_origin="the `OwningGoMod` rule",
        ),
    )

    # Sort by address.spec_path in descending order so the nearest go_mod target is sorted first.
    go_mod_targets = sorted(
        (tgt for tgt in candidate_targets if tgt.has_field(GoModSourcesField)),
        key=lambda tgt: tgt.address.spec_path,
        reverse=True,
    )
    if not go_mod_targets:
        raise InvalidTargetException(
            f"The target {request.address} does not have a `go_mod` target in its BUILD file or "
            "any ancestor BUILD files. To fix, please make sure your project has a `go.mod` file "
            f"and add a `go_mod` target (you can run `{bin_name()} tailor` to do this)."
        )
    nearest_go_mod_target = go_mod_targets[0]
    return OwningGoMod(nearest_go_mod_target.address)


@dataclass(frozen=True)
class GoModInfo:
    # Import path of the Go module, based on the `module` in `go.mod`.
    import_path: str
    digest: Digest
    mod_path: str
    minimum_go_version: str | None


@dataclass(frozen=True)
class GoModInfoRequest(EngineAwareParameter):
    source: Address | GoModSourcesField

    def debug_hint(self) -> str:
        if isinstance(self.source, Address):
            return self.source.spec
        else:
            return self.source.address.spec


@rule
async def determine_go_mod_info(
    request: GoModInfoRequest,
) -> GoModInfo:
    if isinstance(request.source, Address):
        wrapped_target = await Get(
            WrappedTarget,
            WrappedTargetRequest(request.source, description_of_origin="<go mod info rule>"),
        )
        sources_field = wrapped_target.target[GoModSourcesField]
    else:
        sources_field = request.source
    go_mod_path = sources_field.go_mod_path
    go_mod_dir = os.path.dirname(go_mod_path)

    # Get the `go.mod` (and `go.sum`) and strip so the file has no directory prefix.
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(sources_field))
    sources_digest = hydrated_sources.snapshot.digest

    mod_json = await Get(
        ProcessResult,
        GoSdkProcess(
            command=("mod", "edit", "-json"),
            input_digest=sources_digest,
            working_dir=go_mod_dir,
            description=f"Parse {go_mod_path}",
        ),
    )
    module_metadata = json.loads(mod_json.stdout)
    return GoModInfo(
        import_path=module_metadata["Module"]["Path"],
        digest=sources_digest,
        mod_path=go_mod_path,
        minimum_go_version=module_metadata.get("Go"),
    )


def rules():
    return collect_rules()
