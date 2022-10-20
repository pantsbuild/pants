# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.lint.pylint.subsystem import (
    Pylint,
    PylintFieldSet,
    PylintFirstPartyPlugins,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
from pants.backend.python.util_rules.partition import (
    _partition_by_interpreter_constraints_and_resolve,
)
from pants.backend.python.util_rules.pex import (
    Pex,
    PexRequest,
    VenvPex,
    VenvPexProcess,
    VenvPexRequest,
)
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
)
from pants.core.goals.lint import REPORT_DIR, LintResult, LintTargetsRequest, Partitions
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.partitions import Partition
from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, RemovePrefix
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTargets, CoarsenedTargetsRequest
from pants.util.logging import LogLevel
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class PartitionMetadata:
    coarsened_targets: CoarsenedTargets
    # NB: These are the same across every element in a partition
    resolve_description: str | None
    interpreter_constraints: InterpreterConstraints

    @property
    def description(self) -> str:
        ics = str(sorted(str(c) for c in self.interpreter_constraints))
        return f"{self.resolve_description}, {ics}" if self.resolve_description else ics


class PylintRequest(LintTargetsRequest):
    field_set_type = PylintFieldSet
    tool_subsystem = Pylint


def generate_argv(field_sets: tuple[PylintFieldSet, ...], pylint: Pylint) -> Tuple[str, ...]:
    args = []
    if pylint.config is not None:
        args.append(f"--rcfile={pylint.config}")
    args.append("--jobs={pants_concurrency}")
    args.extend(pylint.args)
    args.extend(field_set.source.file_path for field_set in field_sets)
    return tuple(args)


@rule(desc="Determine if necessary to partition Pylint input", level=LogLevel.DEBUG)
async def partition_pylint(
    request: PylintRequest.PartitionRequest[PylintFieldSet],
    pylint: Pylint,
    python_setup: PythonSetup,
    first_party_plugins: PylintFirstPartyPlugins,
) -> Partitions[PylintFieldSet, PartitionMetadata]:
    if pylint.skip:
        return Partitions()

    first_party_ics = InterpreterConstraints.create_from_compatibility_fields(
        first_party_plugins.interpreter_constraints_fields, python_setup
    )

    resolve_and_interpreter_constraints_to_field_sets = (
        _partition_by_interpreter_constraints_and_resolve(request.field_sets, python_setup)
    )

    coarsened_targets = await Get(
        CoarsenedTargets,
        CoarsenedTargetsRequest(field_set.address for field_set in request.field_sets),
    )
    coarsened_targets_by_address = coarsened_targets.by_address()

    return Partitions(
        Partition(
            tuple(field_sets),
            PartitionMetadata(
                CoarsenedTargets(
                    coarsened_targets_by_address[field_set.address] for field_set in field_sets
                ),
                resolve if len(python_setup.resolves) > 1 else None,
                InterpreterConstraints.merge((interpreter_constraints, first_party_ics)),
            ),
        )
        for (
            resolve,
            interpreter_constraints,
        ), field_sets, in resolve_and_interpreter_constraints_to_field_sets.items()
    )


@rule(desc="Lint using Pylint", level=LogLevel.DEBUG)
async def run_pylint(
    request: PylintRequest.Batch[PylintFieldSet, PartitionMetadata],
    pylint: Pylint,
    first_party_plugins: PylintFirstPartyPlugins,
) -> LintResult:
    assert request.partition_metadata is not None

    requirements_pex_get = Get(
        Pex,
        RequirementsPexRequest(
            (target.address for target in request.partition_metadata.coarsened_targets.closure()),
            # NB: These constraints must be identical to the other PEXes. Otherwise, we risk using
            # a different version for the requirements than the other two PEXes, which can result
            # in a PEX runtime error about missing dependencies.
            hardcoded_interpreter_constraints=request.partition_metadata.interpreter_constraints,
        ),
    )

    pylint_pex_get = Get(
        Pex,
        PexRequest,
        pylint.to_pex_request(
            interpreter_constraints=request.partition_metadata.interpreter_constraints,
            extra_requirements=first_party_plugins.requirement_strings,
        ),
    )

    sources_get = Get(
        PythonSourceFiles,
        PythonSourceFilesRequest(request.partition_metadata.coarsened_targets.closure()),
    )
    # Ensure that the empty report dir exists.
    report_directory_digest_get = Get(Digest, CreateDigest([Directory(REPORT_DIR)]))

    (pylint_pex, requirements_pex, sources, report_directory,) = await MultiGet(
        pylint_pex_get,
        requirements_pex_get,
        sources_get,
        report_directory_digest_get,
    )

    pylint_runner_pex, config_files = await MultiGet(
        Get(
            VenvPex,
            VenvPexRequest(
                PexRequest(
                    output_filename="pylint_runner.pex",
                    interpreter_constraints=request.partition_metadata.interpreter_constraints,
                    main=pylint.main,
                    internal_only=True,
                    pex_path=[pylint_pex, requirements_pex],
                ),
                # TODO(John Sirois): Remove this (change to the default of symlinks) when we can
                #  upgrade to a version of Pylint with https://github.com/PyCQA/pylint/issues/1470
                #  resolved.
                site_packages_copies=True,
            ),
        ),
        Get(
            ConfigFiles,
            ConfigFilesRequest,
            pylint.config_request(sources.source_files.snapshot.dirs),
        ),
    )

    pythonpath = list(sources.source_roots)
    if first_party_plugins:
        pythonpath.append(first_party_plugins.PREFIX)

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                config_files.snapshot.digest,
                first_party_plugins.sources_digest,
                sources.source_files.snapshot.digest,
                report_directory,
            )
        ),
    )

    result = await Get(
        FallibleProcessResult,
        VenvPexProcess(
            pylint_runner_pex,
            argv=generate_argv(request.elements, pylint),
            input_digest=input_digest,
            output_directories=(REPORT_DIR,),
            extra_env={"PEX_EXTRA_SYS_PATH": ":".join(pythonpath)},
            concurrency_available=len(request.elements),
            description=f"Run Pylint on {pluralize(len(request.elements), 'target')}.",
            level=LogLevel.DEBUG,
        ),
    )
    report = await Get(Digest, RemovePrefix(result.output_digest, REPORT_DIR))
    return LintResult.create(request, result, report=report)


def rules():
    return [
        *collect_rules(),
        *PylintRequest.rules(),
        *pex_from_targets.rules(),
    ]
