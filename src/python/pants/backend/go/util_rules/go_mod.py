# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from pants.backend.go.target_types import (
    GoBinaryMainPackageField,
    GoModDependenciesField,
    GoModSourcesField,
    GoModTarget,
    GoOwningGoModAddressField,
    GoPackageSourcesField,
    GoThirdPartyPackageDependenciesField,
)
from pants.backend.go.util_rules import binary
from pants.backend.go.util_rules.binary import GoBinaryMainPackage, GoBinaryMainPackageRequest
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.base.specs import AncestorGlobSpec, RawSpecs
from pants.build_graph.address import Address, AddressInput
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.fs import Digest
from pants.engine.process import ProcessResult
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    AllUnexpandedTargets,
    HydratedSources,
    HydrateSourcesRequest,
    InvalidTargetException,
    Targets,
    UnexpandedTargets,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.util.docutil import bin_name
from pants.util.logging import LogLevel

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


class AllGoModTargets(Targets):
    pass


@rule(desc="Find all `go_mod` targets in project", level=LogLevel.DEBUG)
async def find_all_go_mod_targets(targets: AllUnexpandedTargets) -> AllGoModTargets:
    return AllGoModTargets(tgt for tgt in targets if tgt.has_field(GoModDependenciesField))


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


async def _find_explict_owning_go_mod_address(
    address: Address,
    field: GoOwningGoModAddressField,
    alias: str,
    all_go_mod_targets: AllGoModTargets,
) -> Address:
    # If no value is specified, then see if there is only one `go_mod` target in this repository.
    if field.value is None:
        # If so, that is the default.
        if len(all_go_mod_targets) == 1:
            return all_go_mod_targets[0].address

        # Otherwise error and inform user to specify the owning `go_mod` target's address.
        if not all_go_mod_targets:
            raise InvalidTargetException(
                f"The `{alias}` target `{address}` requires that the address of an owning `{GoModTarget.alias}` "
                f"target be given via the `{GoOwningGoModAddressField.alias}` field since it is "
                "a dependency of a Go target. However, there are no `go_mod` targets in this repository."
            )

        raise InvalidTargetException(
            f"The `{alias}` target `{address}` requires that the address of an owning `{GoModTarget.alias}` "
            f"target be given via the `{GoOwningGoModAddressField.alias}` field since it is "
            "a dependency of a Go target. However, there are multiple `go_mod` targets in this repository "
            "which makes the choice of which `go_mod` target to use ambiguous. Please specify which of the "
            "following addresses to use or consider using the `parametrize` builtin to specify more than "
            "one of these addresses if this target will be used in multiple Go modules: "
            f"{', '.join([str(tgt.address) for tgt in all_go_mod_targets])}"
        )

    # If a value is specified, then resolve it as an address.
    address_input = AddressInput.parse(
        field.value,
        relative_to=address.spec_path,
        description_of_origin=f"the `{GoOwningGoModAddressField.alias}` field of target `{address}`",
    )
    candidate_go_mod_address = await Get(Address, AddressInput, address_input)
    wrapped_target = await Get(
        WrappedTarget,
        WrappedTargetRequest(
            candidate_go_mod_address,
            description_of_origin=f"the `{GoOwningGoModAddressField.alias}` field of target `{address}`",
        ),
    )
    if not wrapped_target.target.has_field(GoModDependenciesField):
        raise InvalidTargetException(
            f"The `{alias}` target `{address}` requires that the address of an owning `{GoModTarget.alias}` "
            f"target be given via the `{GoOwningGoModAddressField.alias}` field since it is "
            f"a dependency of a Go target. However, the provided address `{field.value}` does not refer to "
            f"a `{GoModTarget.alias}` target. Please specify which of the following addresses to use or consider "
            "using the `parametrize` builtin to specify more than one of these addresses if this target will be "
            f"used in multiple Go modules: {', '.join([str(tgt.address) for tgt in all_go_mod_targets])}"
        )
    return candidate_go_mod_address


@rule
async def find_owning_go_mod(
    request: OwningGoModRequest, all_go_mod_targets: AllGoModTargets
) -> OwningGoMod:
    wrapped_target = await Get(
        WrappedTarget,
        WrappedTargetRequest(request.address, description_of_origin="the `OwningGoMod` rule"),
    )
    target = wrapped_target.target

    if target.has_field(GoModDependenciesField):
        return OwningGoMod(request.address)

    if target.has_field(GoPackageSourcesField):
        nearest_go_mod_result = await Get(
            NearestAncestorGoModResult, NearestAncestorGoModRequest(request.address)
        )
        return OwningGoMod(nearest_go_mod_result.address)

    if target.has_field(GoThirdPartyPackageDependenciesField):
        # For `go_third_party_package` targets, use the generator which is the owning `go_mod` target.
        generator_address = target.address.maybe_convert_to_target_generator()
        return OwningGoMod(generator_address)

    if target.has_field(GoBinaryMainPackageField):
        main_pkg = await Get(
            GoBinaryMainPackage, GoBinaryMainPackageRequest(target.get(GoBinaryMainPackageField))
        )
        owning_go_mod_for_main_pkg = await Get(OwningGoMod, OwningGoModRequest(main_pkg.address))
        return owning_go_mod_for_main_pkg

    if target.has_field(GoOwningGoModAddressField):
        # Otherwise, find any explicitly defined go_mod address (e.g., for `protobuf_sources` targets).
        explicit_go_mod_address = await _find_explict_owning_go_mod_address(
            address=request.address,
            field=target.get(GoOwningGoModAddressField),
            alias=target.alias,
            all_go_mod_targets=all_go_mod_targets,
        )
        return OwningGoMod(explicit_go_mod_address)

    raise AssertionError(
        f"Internal error: Unable to determine how to determine the owning `{GoModTarget.alias}` target "
        f"for `{target.alias}` target `{target.address}`. Please file an issue at "
        "https://github.com/pantsbuild/pants/issues/new."
    )


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
    return (
        *collect_rules(),
        *binary.rules(),
    )
