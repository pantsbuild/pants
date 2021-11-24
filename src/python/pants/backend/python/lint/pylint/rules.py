# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, List, Tuple

from pants.backend.python.lint.pylint.subsystem import (
    Pylint,
    PylintFieldSet,
    PylintFirstPartyPlugins,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import InterpreterConstraintsField
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.pex import Pex, PexRequest, VenvPex, VenvPexProcess
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.lint import REPORT_DIR, LintRequest, LintResult, LintResults
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses
from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, RemovePrefix
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import DependenciesRequest, Target, Targets
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class PylintTargetSetup:
    field_set: PylintFieldSet
    target_with_dependencies: Targets


@frozen_after_init
@dataclass(unsafe_hash=True)
class PylintPartition:
    field_sets: Tuple[PylintFieldSet, ...]
    targets_with_dependencies: Targets
    interpreter_constraints: InterpreterConstraints

    def __init__(
        self,
        target_setups: Iterable[PylintTargetSetup],
        interpreter_constraints: InterpreterConstraints,
    ) -> None:
        field_sets = []
        targets_with_deps: List[Target] = []
        for target_setup in target_setups:
            field_sets.append(target_setup.field_set)
            targets_with_deps.extend(target_setup.target_with_dependencies)

        self.field_sets = tuple(field_sets)
        self.targets_with_dependencies = Targets(targets_with_deps)
        self.interpreter_constraints = interpreter_constraints


class PylintRequest(LintRequest):
    field_set_type = PylintFieldSet


def generate_argv(source_files: SourceFiles, pylint: Pylint) -> Tuple[str, ...]:
    args = []
    if pylint.config is not None:
        args.append(f"--rcfile={pylint.config}")
    args.extend(pylint.args)
    args.extend(source_files.files)
    return tuple(args)


@rule(level=LogLevel.DEBUG)
async def pylint_lint_partition(
    partition: PylintPartition, pylint: Pylint, first_party_plugins: PylintFirstPartyPlugins
) -> LintResult:
    requirements_pex_get = Get(
        Pex,
        RequirementsPexRequest(
            (field_set.address for field_set in partition.field_sets),
            # NB: These constraints must be identical to the other PEXes. Otherwise, we risk using
            # a different version for the requirements than the other two PEXes, which can result
            # in a PEX runtime error about missing dependencies.
            hardcoded_interpreter_constraints=partition.interpreter_constraints,
            internal_only=True,
            direct_deps_only=True,
        ),
    )

    pylint_pex_get = Get(
        Pex,
        PexRequest(
            output_filename="pylint.pex",
            internal_only=True,
            requirements=pylint.pex_requirements(
                extra_requirements=first_party_plugins.requirement_strings,
            ),
            interpreter_constraints=partition.interpreter_constraints,
        ),
    )

    prepare_python_sources_get = Get(
        PythonSourceFiles, PythonSourceFilesRequest(partition.targets_with_dependencies)
    )
    field_set_sources_get = Get(
        SourceFiles, SourceFilesRequest(field_set.source for field_set in partition.field_sets)
    )
    # Ensure that the empty report dir exists.
    report_directory_digest_get = Get(Digest, CreateDigest([Directory(REPORT_DIR)]))

    (
        pylint_pex,
        requirements_pex,
        prepared_python_sources,
        field_set_sources,
        report_directory,
    ) = await MultiGet(
        pylint_pex_get,
        requirements_pex_get,
        prepare_python_sources_get,
        field_set_sources_get,
        report_directory_digest_get,
    )

    pylint_runner_pex, config_files = await MultiGet(
        Get(
            VenvPex,
            PexRequest(
                output_filename="pylint_runner.pex",
                interpreter_constraints=partition.interpreter_constraints,
                main=pylint.main,
                internal_only=True,
                pex_path=[pylint_pex, requirements_pex],
            ),
        ),
        Get(
            ConfigFiles, ConfigFilesRequest, pylint.config_request(field_set_sources.snapshot.dirs)
        ),
    )

    pythonpath = list(prepared_python_sources.source_roots)
    if first_party_plugins:
        pythonpath.append(first_party_plugins.PREFIX)

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                config_files.snapshot.digest,
                first_party_plugins.sources_digest,
                prepared_python_sources.source_files.snapshot.digest,
                report_directory,
            )
        ),
    )

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            pylint_runner_pex,
            argv=generate_argv(field_set_sources, pylint),
            input_digest=input_digest,
            output_directories=(REPORT_DIR,),
            extra_env={"PEX_EXTRA_SYS_PATH": ":".join(pythonpath)},
            description=f"Run Pylint on {pluralize(len(partition.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    report = await Get(Digest, RemovePrefix(result.output_digest, REPORT_DIR))
    return LintResult.from_fallible_process_result(
        result,
        partition_description=str(sorted(str(c) for c in partition.interpreter_constraints)),
        report=report,
    )


@rule(desc="Lint using Pylint", level=LogLevel.DEBUG)
async def pylint_lint(
    request: PylintRequest,
    pylint: Pylint,
    python_setup: PythonSetup,
    first_party_plugins: PylintFirstPartyPlugins,
) -> LintResults:
    if pylint.skip:
        return LintResults([], linter_name="Pylint")

    # Pylint needs direct dependencies in the chroot to ensure that imports are valid. However, it
    # doesn't lint those direct dependencies nor does it care about transitive dependencies.
    linted_targets = await Get(
        Targets, Addresses(field_set.address for field_set in request.field_sets)
    )
    per_target_dependencies = await MultiGet(
        Get(Targets, DependenciesRequest(field_set.dependencies))
        for field_set in request.field_sets
    )

    # We batch targets by their interpreter constraints to ensure, for example, that all Python 2
    # targets run together and all Python 3 targets run together.
    # Note that Pylint uses the AST of the interpreter that runs it. So, we include any plugin
    # targets in this interpreter constraints calculation.
    interpreter_constraints_to_target_setup = defaultdict(set)
    for field_set, tgt, dependencies in zip(
        request.field_sets, linted_targets, per_target_dependencies
    ):
        target_setup = PylintTargetSetup(field_set, Targets([tgt, *dependencies]))
        interpreter_constraints = InterpreterConstraints.create_from_compatibility_fields(
            (
                *(
                    tgt[InterpreterConstraintsField]
                    for tgt in [tgt, *dependencies]
                    if tgt.has_field(InterpreterConstraintsField)
                ),
                *first_party_plugins.interpreter_constraints_fields,
            ),
            python_setup,
        )
        interpreter_constraints_to_target_setup[interpreter_constraints].add(target_setup)

    partitions = (
        PylintPartition(
            tuple(sorted(target_setups, key=lambda tgt_setup: tgt_setup.field_set.address)),
            interpreter_constraints,
        )
        for interpreter_constraints, target_setups in sorted(
            interpreter_constraints_to_target_setup.items()
        )
    )
    partitioned_results = await MultiGet(
        Get(LintResult, PylintPartition, partition) for partition in partitions
    )
    return LintResults(partitioned_results, linter_name="Pylint")


def rules():
    return [
        *collect_rules(),
        UnionRule(LintRequest, PylintRequest),
        *pex_from_targets.rules(),
    ]
