# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.go.module import FindNearestGoModuleRequest, ResolvedOwningGoModule
from pants.backend.go.pkg import ResolveGoPackageRequest, ResolvedGoPackage
from pants.backend.go.target_types import GoPackageDependencies
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.target import InjectDependenciesRequest, InjectedDependencies
from pants.engine.unions import UnionRule


class InjectGoModuleDependency(InjectDependenciesRequest):
    inject_for = GoPackageDependencies


@rule
async def inject_go_module_dependency(request: InjectGoModuleDependency) -> InjectedDependencies:
    # Resolve the package.
    resolved_go_package = await Get(ResolvedGoPackage, ResolveGoPackageRequest(request.dependencies_field.address.spec_path))

    owning_go_module_result = await Get(
        ResolvedOwningGoModule,
        FindNearestGoModuleRequest(request.dependencies_field.address.spec_path),
    )
    if owning_go_module_result.module_address:
        return InjectedDependencies([owning_go_module_result.module_address])
    else:
        return InjectedDependencies()




def rules():
    return (
        *collect_rules(),
        UnionRule(InjectDependenciesRequest, InjectGoModuleDependency),
    )
