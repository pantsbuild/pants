# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from pants.backend.javascript.subsystems.nodejs import NpxProcess
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    InterpreterConstraintsField,
    PythonResolveField,
    PythonSourceField,
)
from pants.backend.python.typecheck.pyright.subsystem import Pyright
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.partition import (
    _partition_by_interpreter_constraints_and_resolve,
)
from pants.backend.python.util_rules.pex import Pex, PexRequest, VenvPex
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.collection import Collection
from pants.engine.fs import CreateDigest, FileContent
from pants.engine.internals.native_engine import Digest, MergeDigests
from pants.engine.internals.selectors import MultiGet
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import Get, Rule, collect_rules, rule
from pants.engine.target import CoarsenedTargets, CoarsenedTargetsRequest, FieldSet
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class PyrightFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    sources: PythonSourceField
    resolve: PythonResolveField
    interpreter_constraints: InterpreterConstraintsField


class PyrightRequest(CheckRequest):
    field_set_type = PyrightFieldSet
    tool_name = Pyright.options_scope


@dataclass(frozen=True)
class PyrightPartition:
    field_sets: FrozenOrderedSet[PyrightFieldSet]
    root_targets: CoarsenedTargets
    resolve_description: str | None
    interpreter_constraints: InterpreterConstraints

    def description(self) -> str:
        ics = str(sorted(str(c) for c in self.interpreter_constraints))
        return f"{self.resolve_description}, {ics}" if self.resolve_description else ics


class PyrightPartitions(Collection[PyrightPartition]):
    pass


@rule(
    desc="Pyright typecheck each partition based on its interpreter_constraints",
    level=LogLevel.DEBUG,
)
async def pyright_typecheck_partition(
    partition: PyrightPartition,
    pyright: Pyright,
    pex_environment: PexEnvironment,
) -> CheckResult:

    root_sources = await Get(
        SourceFiles,
        SourceFilesRequest(fs.sources for fs in partition.field_sets),
    )

    # Grab the inferred and supporting files for the root source files to be typechecked
    coarsened_sources = await Get(
        PythonSourceFiles, PythonSourceFilesRequest(partition.root_targets.closure())
    )

    # See `requirements_venv_pex` for how this will get wrapped in a `VenvPex`.
    requirements_pex = await Get(
        Pex,
        RequirementsPexRequest(
            (fs.address for fs in partition.field_sets),
            hardcoded_interpreter_constraints=partition.interpreter_constraints,
        ),
    )

    requirements_venv_pex = await Get(
        VenvPex,
        PexRequest(
            output_filename="requirements_venv.pex",
            internal_only=True,
            pex_path=[requirements_pex],
            interpreter_constraints=partition.interpreter_constraints,
        ),
    )

    # venv workaround as per: https://github.com/microsoft/pyright/issues/4051
    dummy_config_digest = await Get(
        Digest,
        CreateDigest(
            [
                FileContent(
                    "pyrightconfig.json",
                    f'{{ "venv": "{requirements_venv_pex.venv_rel_dir}" }}'.encode(),
                )
            ]
        ),
    )

    input_digest = await Get(
        Digest,
        MergeDigests(
            [
                coarsened_sources.source_files.snapshot.digest,
                requirements_venv_pex.digest,
                dummy_config_digest,
            ]
        ),
    )

    complete_pex_env = pex_environment.in_workspace()
    process = await Get(
        Process,
        NpxProcess(
            npm_package=pyright.version,
            args=(
                f"--venv-path={complete_pex_env.pex_root}",  # Used with `venv` in config
                *pyright.args,  # User-added arguments
                *root_sources.snapshot.files,
            ),
            input_digest=input_digest,
            description=f"Run Pyright on {pluralize(len(root_sources.snapshot.files), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    result = await Get(FallibleProcessResult, Process, process)
    return CheckResult.from_fallible_process_result(
        result,
        partition_description=partition.description(),
    )


@rule(
    desc="Determine if it is necessary to partition Pyright's input (interpreter_constraints and resolves)",
    level=LogLevel.DEBUG,
)
async def pyright_determine_partitions(
    request: PyrightRequest,
    pyright: Pyright,
    python_setup: PythonSetup,
) -> PyrightPartitions:

    resolve_and_interpreter_constraints_to_field_sets = (
        _partition_by_interpreter_constraints_and_resolve(request.field_sets, python_setup)
    )

    coarsened_targets = await Get(
        CoarsenedTargets,
        CoarsenedTargetsRequest(field_set.address for field_set in request.field_sets),
    )
    coarsened_targets_by_address = coarsened_targets.by_address()

    return PyrightPartitions(
        PyrightPartition(
            FrozenOrderedSet(field_sets),
            CoarsenedTargets(
                OrderedSet(
                    coarsened_targets_by_address[field_set.address] for field_set in field_sets
                )
            ),
            resolve if len(python_setup.resolves) > 1 else None,
            interpreter_constraints or pyright.interpreter_constraints,
        )
        for (resolve, interpreter_constraints), field_sets in sorted(
            resolve_and_interpreter_constraints_to_field_sets.items()
        )
    )


@rule(desc="Typecheck using Pyright", level=LogLevel.DEBUG)
async def pyright_typecheck(
    request: PyrightRequest,
    pyright: Pyright,
) -> CheckResults:
    if pyright.skip:
        return CheckResults([], checker_name=request.tool_name)

    partitions = await Get(PyrightPartitions, PyrightRequest, request)
    partitioned_results = await MultiGet(
        Get(CheckResult, PyrightPartition, partition) for partition in partitions
    )
    return CheckResults(
        partitioned_results,
        checker_name=request.tool_name,
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *pex_from_targets.rules(),
        UnionRule(CheckRequest, PyrightRequest),
    )
