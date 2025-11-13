# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

import packaging

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
    VenvPexProcess,
    VenvPexRequest,
    create_pex,
    create_venv_pex,
    determine_pex_resolve_info,
)
from pants.backend.python.util_rules.pex_environment import PexEnvironment
from pants.backend.python.util_rules.pex_from_targets import RequirementsPexRequest
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFilesRequest,
    prepare_python_sources,
)
from pants.core.goals.lint import REPORT_DIR, LintResult, LintTargetsRequest, Partitions
from pants.core.util_rules.config_files import find_config_file
from pants.core.util_rules.partitions import Partition
from pants.engine.fs import CreateDigest, Directory, MergeDigests, RemovePrefix
from pants.engine.internals.graph import resolve_coarsened_targets as coarsened_targets_get
from pants.engine.intrinsics import create_digest, execute_process, merge_digests, remove_prefix
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
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
    tool_subsystem = Pylint  # type: ignore[assignment]


def generate_argv(field_sets: tuple[PylintFieldSet, ...], pylint: Pylint) -> tuple[str, ...]:
    args: list[str] = []
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
        first_party_plugins.interpreter_constraints_and_resolve_fields, python_setup
    )

    resolve_and_interpreter_constraints_to_field_sets = (
        _partition_by_interpreter_constraints_and_resolve(request.field_sets, python_setup)
    )

    coarsened_targets = await coarsened_targets_get(
        CoarsenedTargetsRequest(field_set.address for field_set in request.field_sets),
        **implicitly(),
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
        ), field_sets in resolve_and_interpreter_constraints_to_field_sets.items()
    )


@rule(desc="Lint using Pylint", level=LogLevel.DEBUG)
async def run_pylint(
    request: PylintRequest.Batch[PylintFieldSet, PartitionMetadata],
    pylint: Pylint,
    first_party_plugins: PylintFirstPartyPlugins,
    pex_environment: PexEnvironment,
) -> LintResult:
    assert request.partition_metadata is not None

    # The coarsened targets in the incoming request are for all targets in the request's original
    # partition. Since the core `lint` logic re-batches inputs according to `[lint].batch_size`,
    # this could be many more targets than are actually needed to lint the specific batch of files
    # received by this rule. Subset the CTs one more time here to only those that are relevant.
    all_coarsened_targets_by_address = request.partition_metadata.coarsened_targets.by_address()
    coarsened_targets = CoarsenedTargets(
        all_coarsened_targets_by_address[field_set.address] for field_set in request.elements
    )
    coarsened_closure = tuple(coarsened_targets.closure())

    requirements_pex_get = create_pex(
        **implicitly(
            RequirementsPexRequest(
                (target.address for target in coarsened_closure),
                # NB: These constraints must be identical to the other PEXes. Otherwise, we risk using
                # a different version for the requirements than the other two PEXes, which can result
                # in a PEX runtime error about missing dependencies.
                hardcoded_interpreter_constraints=request.partition_metadata.interpreter_constraints,
            )
        )
    )

    pylint_pex_get = create_pex(
        pylint.to_pex_request(
            interpreter_constraints=request.partition_metadata.interpreter_constraints,
            extra_requirements=first_party_plugins.requirement_strings,
        )
    )

    sources_get = prepare_python_sources(
        PythonSourceFilesRequest(coarsened_closure), **implicitly()
    )
    # Ensure that the empty report dir exists.
    report_directory_digest_get = create_digest(CreateDigest([Directory(REPORT_DIR)]))

    (
        pylint_pex,
        requirements_pex,
        sources,
        report_directory,
    ) = await concurrently(
        pylint_pex_get,
        requirements_pex_get,
        sources_get,
        report_directory_digest_get,
    )

    pylint_pex_info = await determine_pex_resolve_info(**implicitly({pylint_pex: Pex}))
    astroid_info = pylint_pex_info.find("astroid")
    # Astroid is a transitive dependency of pylint and should always be available in the pex.
    assert astroid_info

    pylint_runner_pex, config_files = await concurrently(
        create_venv_pex(
            VenvPexRequest(
                PexRequest(
                    output_filename="pylint_runner.pex",
                    interpreter_constraints=request.partition_metadata.interpreter_constraints,
                    main=pylint.main,
                    internal_only=True,
                    pex_path=[pylint_pex, requirements_pex],
                ),
                pex_environment.in_sandbox(working_directory=None),
                # Astroid < 2.9.1 had a regression that prevented the use of symlinks:
                # https://github.com/PyCQA/pylint/issues/1470
                site_packages_copies=(astroid_info.version < packaging.version.Version("2.9.1")),
            ),
            **implicitly(),
        ),
        find_config_file(pylint.config_request(sources.source_files.snapshot.dirs)),
    )

    pythonpath = list(sources.source_roots)
    if first_party_plugins:
        pythonpath.append(first_party_plugins.PREFIX)

    input_digest = await merge_digests(
        MergeDigests(
            (
                config_files.snapshot.digest,
                first_party_plugins.sources_digest,
                sources.source_files.snapshot.digest,
                report_directory,
            )
        )
    )

    result = await execute_process(
        **implicitly(
            VenvPexProcess(
                pylint_runner_pex,
                argv=generate_argv(request.elements, pylint),
                input_digest=input_digest,
                output_directories=(REPORT_DIR,),
                extra_env={"PEX_EXTRA_SYS_PATH": ":".join(pythonpath)},
                concurrency_available=len(request.elements),
                description=f"Run Pylint on {pluralize(len(request.elements), 'target')}.",
                level=LogLevel.DEBUG,
            )
        )
    )
    report = await remove_prefix(RemovePrefix(result.output_digest, REPORT_DIR))
    return LintResult.create(request, result, report=report)


def rules():
    return (
        *collect_rules(),
        *PylintRequest.rules(),
        *pex_from_targets.rules(),
    )
