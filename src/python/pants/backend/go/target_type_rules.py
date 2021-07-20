# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.go.target_types import GoModuleGoVersion, GoPackageDependencies
from pants.base.specs import AddressSpecs, AscendantAddresses, SiblingAddresses
from pants.build_graph.address import Address
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import (
    InjectDependenciesRequest,
    InjectedDependencies,
    Targets,
    WrappedTarget,
)
from pants.engine.unions import UnionRule


class InjectGoModuleDependency(InjectDependenciesRequest):
    inject_for = GoPackageDependencies


@rule
async def inject_go_module_dependency(request: InjectGoModuleDependency) -> InjectedDependencies:
    original_tgt = await Get(WrappedTarget, Address, request.dependencies_field.address)
    spec_path = original_tgt.target.address.spec_path
    candidate_targets = await Get(
        Targets, AddressSpecs([AscendantAddresses(spec_path), SiblingAddresses(spec_path)])
    )
    go_module_targets = [
        (tgt.address.spec_path, tgt)
        for tgt in candidate_targets
        if tgt.has_field(GoModuleGoVersion)
    ]
    sorted_go_module_targets = sorted(go_module_targets, key=lambda x: x[0], reverse=True)
    if sorted_go_module_targets:
        nearest_go_module_target = sorted_go_module_targets[0][1]
        return InjectedDependencies([nearest_go_module_target.address])
    else:
        # TODO: Consider eventually requiring all go_package's to associate with a go_module.
        return InjectedDependencies()


def rules():
    return (
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectGoModuleDependency),
    )
