# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.python.target_types import PythonRequirementsFile, PythonRequirementTarget
from pants.core.goals.update_build_files import (
    DeprecationFixerRequest,
    RewrittenBuildFile,
    RewrittenBuildFileRequest,
)
from pants.engine.addresses import Address, Addresses
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    AllTargets,
    Dependencies,
    DependenciesRequest,
    ExplicitlyProvidedDependencies,
    MultipleSourcesField,
    UnexpandedTargets,
)
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel


@dataclass(frozen=True, order=True)
class GeneratorRename:
    build_path: str
    alias: str
    new_name: str | None


@dataclass(frozen=True)
class MacroRenames:
    generators: tuple[GeneratorRename, ...]
    generated: FrozenDict[Address, Address]


@rule(desc="Determine how to rename Python macros to target generators", level=LogLevel.DEBUG)
async def determine_macro_changes(all_targets: AllTargets) -> MacroRenames:
    # Strategy: Find `python_requirement` targets who depend on a `_python_requirements_file`
    # target to figure out which macros we have. Note that context-aware object factories (CAOFs)
    # are not actual targets and are "erased", so this is the way to find the macros.
    #
    # We also need to figure out if the new target generator can use the default `name=None` or
    # if it needs to set an explicit name, based on whether it's the build root and whether the
    # default is already taken.

    dirs_with_default_name = set()
    python_requirement_dependencies_fields = set()
    for tgt in all_targets:
        if tgt.address.is_default_target:
            dirs_with_default_name.add(tgt.address.spec_path)
        if isinstance(tgt, PythonRequirementTarget) and tgt[Dependencies].value is not None:
            python_requirement_dependencies_fields.add(tgt[Dependencies])

    explicit_deps_per_tgt = await MultiGet(
        Get(ExplicitlyProvidedDependencies, DependenciesRequest(deps_field))
        for deps_field in python_requirement_dependencies_fields
    )
    deps_per_tgt = await MultiGet(
        Get(UnexpandedTargets, Addresses(explicit_deps.includes))
        for explicit_deps in explicit_deps_per_tgt
    )

    generators = set()
    generated = {}
    for python_req_deps_field, deps in zip(python_requirement_dependencies_fields, deps_per_tgt):
        generator_tgt = next((tgt for tgt in deps if isinstance(tgt, PythonRequirementsFile)), None)
        if generator_tgt is None:
            continue

        # Assume there is a single source. We should have changed this target to use
        # `SingleSourceField`, alas.
        generator_source = generator_tgt[MultipleSourcesField].value[0]  # type: ignore[index]
        if "Pipfile" in generator_source:
            generator_alias = "pipenv_requirements"
        elif "pyproject.toml" in generator_source:
            generator_alias = "poetry_requirements"
        else:
            generator_alias = "python_requirements"

        generator_name: str | None
        if (
            generator_tgt.address.spec_path
            and generator_tgt.address.spec_path not in dirs_with_default_name
        ):
            generator_name = None
        elif generator_alias == "pipenv_requirements":
            generator_name = "pipenv"
        elif generator_alias == "poetry_requirements":
            generator_name = "poetry"
        else:
            generator_name = "reqs"

        generators.add(
            GeneratorRename(generator_tgt.address.spec_path, generator_alias, generator_name)
        )

        generated[python_req_deps_field.address] = Address(
            generator_tgt.address.spec_path,
            target_name=generator_name,
            generated_name=python_req_deps_field.address.target_name,
        )

    return MacroRenames(tuple(sorted(generators)), FrozenDict(sorted(generated.items())))


class UpdatePythonRequirementsRequest(DeprecationFixerRequest):
    pass


@rule(desc="Change Python macros to target generators", level=LogLevel.DEBUG)
def maybe_replace_macros(
    request: UpdatePythonRequirementsRequest,
    renames: MacroRenames,
) -> RewrittenBuildFile:
    return RewrittenBuildFile(request.path, request.lines, change_descriptions=())


def rules():
    return (
        *collect_rules(),
        UnionRule(RewrittenBuildFileRequest, UpdatePythonRequirementsRequest),
    )
