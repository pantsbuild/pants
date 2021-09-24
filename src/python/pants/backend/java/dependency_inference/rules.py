# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import logging
from typing import cast

from pants.backend.java.dependency_inference import import_parser, package_mapper
from pants.backend.java.dependency_inference.import_parser import (
    ParsedJavaImports,
    ParseJavaImportsRequest,
)
from pants.backend.java.dependency_inference.package_mapper import FirstPartyJavaPackageMapping
from pants.backend.java.target_types import JavaSourceField
from pants.engine.addresses import Address
from pants.engine.rules import Get, MultiGet, SubsystemRule, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    InferDependenciesRequest,
    InferredDependencies,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.option.subsystem import Subsystem

logger = logging.getLogger(__name__)


class JavaInferSubsystem(Subsystem):
    options_scope = "java-infer"
    help = "Options controlling which dependencies will be inferred for Java targets."

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--imports",
            default=True,
            type=bool,
            help=(
                "Infer a target's imported dependencies by parsing import statements from sources."
            ),
        )

    @property
    def imports(self) -> bool:
        return cast(bool, self.options.imports)


class InferJavaImportDependencies(InferDependenciesRequest):
    infer_from = JavaSourceField


@rule(desc="Inferring Java dependencies by analyzing imports")
async def infer_java_dependencies_via_imports(
    request: InferJavaImportDependencies,
    java_infer_subsystem: JavaInferSubsystem,
    first_party_dep_map: FirstPartyJavaPackageMapping,
) -> InferredDependencies:
    if not java_infer_subsystem.imports:
        return InferredDependencies([])

    wrapped_tgt = await Get(WrappedTarget, Address, request.sources_field.address)
    explicitly_provided_deps, detected_imports = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(wrapped_tgt.target[Dependencies])),
        Get(
            ParsedJavaImports,
            ParseJavaImportsRequest(
                request.sources_field,
            ),
        ),
    )
    relevant_imports = detected_imports  # TODO: Remove stdlib

    dep_map = first_party_dep_map.package_rooted_dependency_map

    return InferredDependencies(
        dependencies=itertools.chain.from_iterable(
            dep_map.addresses_for_symbol(imp) for imp in relevant_imports
        ),
    )


def rules():
    return [
        infer_java_dependencies_via_imports,
        *import_parser.rules(),
        *package_mapper.rules(),
        SubsystemRule(JavaInferSubsystem),
        UnionRule(InferDependenciesRequest, InferJavaImportDependencies),
    ]
