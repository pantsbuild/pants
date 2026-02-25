# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import (
    InterpreterConstraintsField,
    PythonResolveField,
    PythonSourceField,
)
from pants.backend.python.typecheck.pytype.skip_field import SkipPytypeField
from pants.backend.python.typecheck.pytype.subsystem import Pytype
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.partition import (
    _partition_by_interpreter_constraints_and_resolve,
)
from pants.backend.python.util_rules.pex import (
    PexRequest,
    VenvPexProcess,
    VenvPexRequest,
    create_pex,
    create_venv_pex,
)
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.core.goals.check import CheckRequest, CheckResult, CheckResults, CheckSubsystem
from pants.core.goals.resolves import ExportableTool
from pants.core.util_rules import config_files
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.source_files import SourceFilesRequest, determine_source_files
from pants.engine.collection import Collection
from pants.engine.internals.graph import resolve_coarsened_targets as coarsened_targets_get
from pants.engine.internals.native_engine import MergeDigests
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import execute_process, merge_digests
from pants.engine.rules import Rule, collect_rules, implicitly, rule
from pants.engine.target import CoarsenedTargets, CoarsenedTargetsRequest, FieldSet, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import pluralize

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PytypeFieldSet(FieldSet):
    required_fields = (PythonSourceField,)

    sources: PythonSourceField
    resolve: PythonResolveField
    interpreter_constraints: InterpreterConstraintsField

    @classmethod
    def opt_out(cls, tgt: Target) -> bool:
        return tgt.get(SkipPytypeField).value


class PytypeRequest(CheckRequest):
    field_set_type = PytypeFieldSet
    tool_name = Pytype.options_scope


@dataclass(frozen=True)
class PytypePartition:
    field_sets: FrozenOrderedSet[PytypeFieldSet]
    root_targets: CoarsenedTargets
    resolve_description: str | None
    interpreter_constraints: InterpreterConstraints

    def description(self) -> str:
        ics = str(sorted(str(c) for c in self.interpreter_constraints))
        return f"{self.resolve_description}, {ics}" if self.resolve_description else ics


class PytypePartitions(Collection[PytypePartition]):
    pass


@rule(
    desc="Pytype typecheck each partition based on its interpreter_constraints",
    level=LogLevel.DEBUG,
)
async def pytype_typecheck_partition(
    partition: PytypePartition,
    pytype: Pytype,
    check_subsystem: CheckSubsystem,
    pex_environment: PexEnvironment,
) -> CheckResult:
    roots_sources, requirements_pex, pytype_pex, config_files = await concurrently(
        determine_source_files(SourceFilesRequest(fs.sources for fs in partition.field_sets)),
        create_pex(
            **implicitly(
                RequirementsPexRequest(
                    (fs.address for fs in partition.field_sets),
                    hardcoded_interpreter_constraints=partition.interpreter_constraints,
                )
            )
        ),
        create_pex(
            pytype.to_pex_request(interpreter_constraints=partition.interpreter_constraints)
        ),
        find_config_file(pytype.config_request()),
    )

    input_digest = await merge_digests(
        MergeDigests((roots_sources.snapshot.digest, config_files.snapshot.digest))
    )

    runner = await create_venv_pex(
        VenvPexRequest(
            PexRequest(
                output_filename="pytype_runner.pex",
                interpreter_constraints=partition.interpreter_constraints,
                main=pytype.main,
                internal_only=True,
                pex_path=[pytype_pex, requirements_pex],
            ),
            pex_environment.in_sandbox(working_directory=None),
        ),
        **implicitly(),
    )

    result = await execute_process(
        **implicitly(
            VenvPexProcess(
                runner,
                argv=(
                    *(("--config", pytype.config) if pytype.config else ()),
                    "{pants_concurrency}",
                    *pytype.args,
                    *roots_sources.files,
                ),
                # This adds the venv/bin folder to PATH
                extra_env={
                    "PEX_VENV_BIN_PATH": "prepend",
                },
                input_digest=input_digest,
                output_files=roots_sources.files,
                concurrency_available=len(roots_sources.files),
                description=f"Run Pytype on {pluralize(len(roots_sources.files), 'file')}.",
                level=LogLevel.DEBUG,
                cache_scope=check_subsystem.default_process_cache_scope,
            )
        )
    )

    return CheckResult.from_fallible_process_result(
        result,
        partition_description=partition.description(),
    )


@rule(
    desc="Determine if it is necessary to partition Pytype's input (interpreter_constraints and resolves)",
    level=LogLevel.DEBUG,
)
async def pytype_determine_partitions(
    request: PytypeRequest,
    pytype: Pytype,
    python_setup: PythonSetup,
) -> PytypePartitions:
    resolve_and_interpreter_constraints_to_field_sets = (
        _partition_by_interpreter_constraints_and_resolve(request.field_sets, python_setup)
    )

    coarsened_targets = await coarsened_targets_get(
        CoarsenedTargetsRequest(field_set.address for field_set in request.field_sets),
        **implicitly(),
    )
    coarsened_targets_by_address = coarsened_targets.by_address()

    return PytypePartitions(
        PytypePartition(
            FrozenOrderedSet(field_sets),
            CoarsenedTargets(
                OrderedSet(
                    coarsened_targets_by_address[field_set.address] for field_set in field_sets
                )
            ),
            resolve if len(python_setup.resolves) > 1 else None,
            interpreter_constraints or pytype.interpreter_constraints,
        )
        for (resolve, interpreter_constraints), field_sets in sorted(
            resolve_and_interpreter_constraints_to_field_sets.items()
        )
    )


@rule(desc="Typecheck using Pytype", level=LogLevel.DEBUG)
async def pytype_typecheck(
    request: PytypeRequest,
    pytype: Pytype,
) -> CheckResults:
    if pytype.skip:
        return CheckResults([], checker_name=request.tool_name)

    # Explicitly excluding `pytype` as a function argument to `pytype_determine_partitions` and `pytype_typecheck_partition`
    # as it throws "TypeError: unhashable type: 'Pytype'"
    partitions = await pytype_determine_partitions(request, **implicitly())
    partitioned_results = await concurrently(
        pytype_typecheck_partition(partition, **implicitly()) for partition in partitions
    )
    return CheckResults(
        partitioned_results,
        checker_name=request.tool_name,
    )


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        *config_files.rules(),
        *pex_from_targets.rules(),
        UnionRule(CheckRequest, PytypeRequest),
        UnionRule(ExportableTool, Pytype),
    )
