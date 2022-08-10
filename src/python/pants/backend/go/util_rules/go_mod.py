# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from pants.backend.go.target_types import (
    GoModSourcesField,
    GoPackageSourcesField,
    GoThirdPartyPackageDependenciesField,
)
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.backend.project_info.dependees import Dependees, DependeesRequest
from pants.base.specs import AncestorGlobSpec, RawSpecs
from pants.build_graph.address import Address
from pants.engine.addresses import Addresses
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import Digest
from pants.engine.internals.selectors import MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule, rule_helper
from pants.engine.target import (
    HydratedSources,
    HydrateSourcesRequest,
    InvalidTargetException,
    Targets,
    UnexpandedTargets,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.util.docutil import bin_name
from pants.util.strutil import bullet_list

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OwningGoModRequest(EngineAwareParameter):
    address: Address

    def debug_hint(self) -> str:
        return self.address.spec


@dataclass(frozen=True)
class OwningGoMod:
    address: Address


@dataclass(frozen=True)
class NearestAncestorGoModRequest(EngineAwareParameter):
    address: Address

    def debug_hint(self) -> str | None:
        return self.address.spec


@dataclass(frozen=True)
class NearestAncestorGoModResult:
    address: Address


@rule
async def find_nearest_ancestor_go_mod(
    request: NearestAncestorGoModRequest,
) -> NearestAncestorGoModResult:
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

    return NearestAncestorGoModResult(go_mod_targets[0].address)


@rule_helper
async def _find_go_mod_dependee(address: Address) -> Address:
    # Find all targets that depend on the given target.
    dependees = await Get(
        Dependees,
        DependeesRequest(
            addresses=(address,),
            transitive=True,
            include_roots=False,
        ),
    )

    # Resolve the owning `go_mod` targets for `go_package` targets in the dependees set.
    targets = await Get(Targets, Addresses(dependees))
    owning_go_mods = await MultiGet(
        Get(NearestAncestorGoModResult, NearestAncestorGoModRequest(tgt.address))
        for tgt in targets
        if tgt.has_field(GoPackageSourcesField)
    )

    owning_go_mods_set = set(x.address for x in owning_go_mods)
    if len(owning_go_mods_set) > 1:
        addr_bullet_list = bullet_list([str(addr) for addr in owning_go_mods_set])
        raise InvalidTargetException(
            f"The target {address} has multiple `go_mod` targets as dependees. Pants currently is limited to "
            "supporting a single `go_mod` target as a dependee for non-`go_package` targets. The dependee "
            f"`go_mod` targets are:\n\n{addr_bullet_list}"
        )
    elif len(owning_go_mods_set) == 0:
        raise InvalidTargetException(
            f"The target {address} does not have a `go_mod` target as a dependee. This error should not have "
            "happened because {address} is not part of the dependency graph of any Go-related target. "
            "Please open an issue at https://github.com/pantsbuild/pants/issues/new/choose"
        )

    return list(owning_go_mods_set)[0]


@rule
async def find_owning_go_mod(request: OwningGoModRequest) -> OwningGoMod:
    wrapped_target = await Get(
        WrappedTarget,
        WrappedTargetRequest(request.address, description_of_origin="the `OwningGoMod` rule"),
    )
    target = wrapped_target.target

    if target.has_field(GoModSourcesField):
        return OwningGoMod(request.address)
    elif target.has_field(GoPackageSourcesField):
        # For `go_package` targets, use the nearest ancestor go_mod target.
        nearest_go_mod_result = await Get(
            NearestAncestorGoModResult, NearestAncestorGoModRequest(request.address)
        )
        return OwningGoMod(nearest_go_mod_result.address)
    elif target.has_field(GoThirdPartyPackageDependenciesField):
        # For `go_third_party_package` targets, use the generator which is the owning `go_mod` target.
        generator_address = target.address.maybe_convert_to_target_generator()
        return OwningGoMod(generator_address)
    else:
        # Otherwise, find the nearest ancestor dependency that is a go_package() and use its owning go_mod.
        go_mod_dependee = await _find_go_mod_dependee(request.address)
        return OwningGoMod(go_mod_dependee)


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
