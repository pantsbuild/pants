# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.go.target_types import GoModuleSources, GoPackageDependencies
from pants.base.specs import AddressSpecs, AscendantAddresses, SiblingAddresses
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import InjectDependenciesRequest, InjectedDependencies, UnexpandedTargets
from pants.engine.unions import UnionRule


class InjectGoModuleDependency(InjectDependenciesRequest):
    inject_for = GoPackageDependencies


@rule
async def inject_go_module_dependency(request: InjectGoModuleDependency) -> InjectedDependencies:
    # Obtain unexpanded targets and ensure file targets are filtered out. Unlike Python, file targets do not
    # make sense semantically for Go source since Go builds entire packages at a time. The filtering is
    # accomplished by requesting `UnexpandedTargets` and also filtering on `is_file_target`.
    spec_path = request.dependencies_field.address.spec_path
    candidate_targets = await Get(
        UnexpandedTargets,
        AddressSpecs([AscendantAddresses(spec_path), SiblingAddresses(spec_path)]),
    )
    go_module_targets = [
        tgt
        for tgt in candidate_targets
        if tgt.has_field(GoModuleSources) and not tgt.address.is_file_target
    ]

    # Sort by address.spec_path in descending order so the nearest go_module target is sorted first.
    sorted_go_module_targets = sorted(
        go_module_targets, key=lambda tgt: tgt.address.spec_path, reverse=True
    )
    if sorted_go_module_targets:
        nearest_go_module_target = sorted_go_module_targets[0]
        return InjectedDependencies([nearest_go_module_target.address])
    else:
        # TODO: Consider eventually requiring all go_package's to associate with a go_module.
        return InjectedDependencies()


def rules():
    return (
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectGoModuleDependency),
    )
