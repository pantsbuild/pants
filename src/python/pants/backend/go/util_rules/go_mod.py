# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import ijson

from pants.backend.go.target_types import GoModSourcesField
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.base.specs import AddressSpecs, AscendantAddresses, MaybeEmptySiblingAddresses
from pants.build_graph.address import Address
from pants.engine.fs import Digest, DigestSubset, PathGlobs, RemovePrefix
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    UnexpandedTargets,
    WrappedTarget,
)
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModuleDescriptor:
    path: str
    version: str


@dataclass(frozen=True)
class GoModInfo:
    # Import path of the Go module, based on the `module` in `go.mod`.
    import_path: str

    # Modules referenced by this go.mod with resolved versions.
    modules: FrozenOrderedSet[ModuleDescriptor]

    # Digest containing the full paths to `go.mod` and `go.sum`.
    digest: Digest

    # Digest containing only the `go.sum` with no leading directory prefix.
    go_sum_stripped_digest: Digest


@dataclass(frozen=True)
class GoModInfoRequest:
    address: Address


def parse_module_descriptors(raw_json: bytes) -> list[ModuleDescriptor]:
    """Parse the JSON output of `go list -m`."""
    if not raw_json:
        return []

    module_descriptors = []
    for raw_module_descriptor in ijson.items(raw_json, "", multiple_values=True):
        if raw_module_descriptor.get("Main", False):
            continue

        module_descriptor = ModuleDescriptor(
            path=raw_module_descriptor["Path"],
            version=raw_module_descriptor["Version"],
        )
        module_descriptors.append(module_descriptor)
    return module_descriptors


@rule
async def resolve_go_module(
    request: GoModInfoRequest,
) -> GoModInfo:
    wrapped_target = await Get(WrappedTarget, Address, request.address)
    sources_field = wrapped_target.target[GoModSourcesField]

    # Get the `go.mod` (and `go.sum`) and strip so the file has no directory prefix.
    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(sources_field))
    sources_without_prefix = await Get(
        Digest, RemovePrefix(hydrated_sources.snapshot.digest, request.address.spec_path)
    )
    go_sum_digest_get = Get(Digest, DigestSubset(sources_without_prefix, PathGlobs(["go.sum"])))

    mod_json_get = Get(
        ProcessResult,
        GoSdkProcess(
            command=("mod", "edit", "-json"),
            input_digest=sources_without_prefix,
            description=f"Parse {sources_field.go_mod_path}",
        ),
    )
    list_modules_get = Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=sources_without_prefix,
            command=("list", "-m", "-json", "all"),
            description=f"List modules in {sources_field.go_mod_path}",
        ),
    )

    mod_json, list_modules, go_sum_digest = await MultiGet(
        mod_json_get, list_modules_get, go_sum_digest_get
    )

    module_metadata = json.loads(mod_json.stdout)
    modules = parse_module_descriptors(list_modules.stdout)
    return GoModInfo(
        import_path=module_metadata["Module"]["Path"],
        modules=FrozenOrderedSet(modules),
        digest=hydrated_sources.snapshot.digest,
        go_sum_stripped_digest=go_sum_digest,
    )


@dataclass(frozen=True)
class OwningGoModRequest:
    spec_path: str


@dataclass(frozen=True)
class OwningGoMod:
    address: Address | None


@rule
async def find_nearest_go_module(request: OwningGoModRequest) -> OwningGoMod:
    spec_path = request.spec_path
    candidate_targets = await Get(
        UnexpandedTargets,
        AddressSpecs([AscendantAddresses(spec_path), MaybeEmptySiblingAddresses(spec_path)]),
    )
    go_module_targets = [tgt for tgt in candidate_targets if tgt.has_field(GoModSourcesField)]

    # Sort by address.spec_path in descending order so the nearest go_module target is sorted first.
    sorted_go_module_targets = sorted(
        go_module_targets, key=lambda tgt: tgt.address.spec_path, reverse=True
    )
    if sorted_go_module_targets:
        nearest_go_module_target = sorted_go_module_targets[0]
        return OwningGoMod(nearest_go_module_target.address)
    # TODO: Consider eventually requiring all go_package's to associate with a go_module.
    return OwningGoMod(None)


def rules():
    return collect_rules()
