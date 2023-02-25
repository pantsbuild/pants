# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.backend.go.target_types import (
    GoBinaryDependenciesField,
    GoBinaryMainPackageField,
    GoImportPathField,
    GoPackageSourcesField,
)
from pants.base.specs import DirGlobSpec, RawSpecs
from pants.build_graph.address import Address, AddressInput, ResolveError
from pants.engine.engine_aware import EngineAwareParameter
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    FieldSet,
    InferDependenciesRequest,
    InferredDependencies,
    InvalidFieldException,
    Targets,
    WrappedTarget,
    WrappedTargetRequest,
)
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class GoBinaryMainPackage:
    address: Address

    is_third_party: bool
    import_path: str | None = None


@dataclass(frozen=True)
class GoBinaryMainPackageRequest(EngineAwareParameter):
    field: GoBinaryMainPackageField

    def debug_hint(self) -> str:
        return self.field.address.spec


@rule(desc="Determine first-party package used by `go_binary` target", level=LogLevel.DEBUG)
async def determine_main_pkg_for_go_binary(
    request: GoBinaryMainPackageRequest,
) -> GoBinaryMainPackage:
    addr = request.field.address
    if request.field.value:
        description_of_origin = (
            f"the `{request.field.alias}` field from the target {request.field.address}"
        )
        specified_address = await Get(
            Address,
            AddressInput,
            AddressInput.parse(
                request.field.value,
                relative_to=addr.spec_path,
                description_of_origin=description_of_origin,
            ),
        )
        wrapped_specified_tgt = await Get(
            WrappedTarget,
            WrappedTargetRequest(specified_address, description_of_origin=description_of_origin),
        )
        if not wrapped_specified_tgt.target.has_field(
            GoPackageSourcesField
        ) and not wrapped_specified_tgt.target.has_field(GoImportPathField):
            raise InvalidFieldException(
                f"The {repr(GoBinaryMainPackageField.alias)} field in target {addr} must point to "
                "a `go_package` or `go_third_party_package` target, but was the address for a "
                f"`{wrapped_specified_tgt.target.alias}` target.\n\n"
                "Hint: unless the package is a `go_third_party_package` target, you should normally "
                "not specify this field for local packages so that Pants will find the `go_package` "
                "target for you."
            )

        if not wrapped_specified_tgt.target.has_field(GoPackageSourcesField):
            return GoBinaryMainPackage(
                wrapped_specified_tgt.target.address,
                is_third_party=True,
                import_path=wrapped_specified_tgt.target.get(GoImportPathField).value,
            )
        return GoBinaryMainPackage(wrapped_specified_tgt.target.address, is_third_party=False)

    candidate_targets = await Get(
        Targets,
        RawSpecs(
            dir_globs=(DirGlobSpec(addr.spec_path),),
            description_of_origin="the `go_binary` dependency inference rule",
        ),
    )
    relevant_pkg_targets = [
        tgt
        for tgt in candidate_targets
        if tgt.has_field(GoPackageSourcesField) and tgt.residence_dir == addr.spec_path
    ]
    if len(relevant_pkg_targets) == 1:
        return GoBinaryMainPackage(relevant_pkg_targets[0].address, is_third_party=False)

    if not relevant_pkg_targets:
        raise ResolveError(
            f"The target {addr} requires that there is a `go_package` "
            f"target defined in its directory {addr.spec_path}, but none were found.\n\n"
            "To fix, add a target like `go_package()` or `go_package(name='pkg')` to the BUILD "
            f"file in {addr.spec_path}."
        )
    raise ResolveError(
        f"There are multiple `go_package` targets for the same directory of the "
        f"target {addr}: {addr.spec_path}. It is ambiguous what to use as the `main` "
        "package.\n\n"
        f"To fix, please either set the `main` field for `{addr} or remove these "
        "`go_package` targets so that only one remains: "
        f"{sorted(tgt.address.spec for tgt in relevant_pkg_targets)}"
    )


@dataclass(frozen=True)
class GoBinaryMainDependencyInferenceFieldSet(FieldSet):
    required_fields = (GoBinaryDependenciesField, GoBinaryMainPackageField)

    dependencies: GoBinaryDependenciesField
    main_package: GoBinaryMainPackageField


class InferGoBinaryMainDependencyRequest(InferDependenciesRequest):
    infer_from = GoBinaryMainDependencyInferenceFieldSet


@rule
async def infer_go_binary_main_dependency(
    request: InferGoBinaryMainDependencyRequest,
) -> InferredDependencies:
    main_pkg = await Get(
        GoBinaryMainPackage,
        GoBinaryMainPackageRequest(request.field_set.main_package),
    )
    return InferredDependencies([main_pkg.address])


def rules():
    return (
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferGoBinaryMainDependencyRequest),
    )
