# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Mapping, Tuple

from pants.backend.python.lint.pylint.subsystem import (
    Pylint,
    PylintFieldSet,
    PylintFirstPartyPlugins,
)
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import InterpreterConstraintsField, PythonResolveField
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.interpreter_constraints import InterpreterConstraints
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
from pants.core.goals.lint import REPORT_DIR, LintResult, LintResults, LintTargetsRequest
from pants.core.util_rules.config_files import ConfigFiles, ConfigFilesRequest
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.collection import Collection
from pants.engine.fs import CreateDigest, Digest, Directory, MergeDigests, RemovePrefix
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import CoarsenedTarget, CoarsenedTargets, CoarsenedTargetsRequest, Target
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel
from pants.util.ordered_set import FrozenOrderedSet, OrderedSet
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class PylintPartition:
    root_field_sets: FrozenOrderedSet[PylintFieldSet]
    closure: FrozenOrderedSet[Target]
    resolve_description: str | None
    interpreter_constraints: InterpreterConstraints

    def description(self) -> str:
        ics = str(sorted(str(c) for c in self.interpreter_constraints))
        return f"{self.resolve_description}, {ics}" if self.resolve_description else ics


class PylintPartitions(Collection[PylintPartition]):
    pass


class PylintRequest(LintTargetsRequest):
    field_set_type = PylintFieldSet
    name = Pylint.options_scope


def generate_argv(source_files: SourceFiles, pylint: Pylint) -> Tuple[str, ...]:
    args = []
    if pylint.config is not None:
        args.append(f"--rcfile={pylint.config}")
    args.append("--jobs={pants_concurrency}")
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
            (fs.address for fs in partition.root_field_sets),
            # NB: These constraints must be identical to the other PEXes. Otherwise, we risk using
            # a different version for the requirements than the other two PEXes, which can result
            # in a PEX runtime error about missing dependencies.
            hardcoded_interpreter_constraints=partition.interpreter_constraints,
        ),
    )

    pylint_pex_get = Get(
        Pex,
        PexRequest,
        pylint.to_pex_request(
            interpreter_constraints=partition.interpreter_constraints,
            extra_requirements=first_party_plugins.requirement_strings,
        ),
    )

    prepare_python_sources_get = Get(PythonSourceFiles, PythonSourceFilesRequest(partition.closure))
    field_set_sources_get = Get(
        SourceFiles, SourceFilesRequest(fs.source for fs in partition.root_field_sets)
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
            VenvPexRequest(
                PexRequest(
                    output_filename="pylint_runner.pex",
                    interpreter_constraints=partition.interpreter_constraints,
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
            concurrency_available=len(partition.root_field_sets),
            description=f"Run Pylint on {pluralize(len(partition.root_field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    report = await Get(Digest, RemovePrefix(result.output_digest, REPORT_DIR))
    return LintResult.from_fallible_process_result(
        result,
        partition_description=partition.description(),
        report=report,
    )


# TODO(#15241): Improve the performance of this, especially by not needing to calculate transitive
#  targets per field set. Doing that would require changing how we calculate interpreter
#  constraints to be more like how we determine resolves, i.e. only inspecting the root target
#  (and later validating the closure is compatible).
@rule(desc="Determine if necessary to partition Pylint input", level=LogLevel.DEBUG)
async def pylint_determine_partitions(
    request: PylintRequest, python_setup: PythonSetup, first_party_plugins: PylintFirstPartyPlugins
) -> PylintPartitions:
    # We batch targets by their interpreter constraints + resolve to ensure, for example, that all
    # Python targets run together and all Python 3 targets run together.
    #
    # Note that Pylint uses the AST of the interpreter that runs it. So, we include any plugin
    # targets in this interpreter constraints calculation. However, we don't have to consider the
    # resolve of the plugin targets, per https://github.com/pantsbuild/pants/issues/14320.
    coarsened_targets = await Get(
        CoarsenedTargets,
        CoarsenedTargetsRequest(
            (field_set.address for field_set in request.field_sets), expanded_targets=True
        ),
    )
    coarsened_targets_by_address = coarsened_targets.by_address()

    resolve_and_interpreter_constraints_to_coarsened_targets: Mapping[
        tuple[str, InterpreterConstraints],
        tuple[OrderedSet[PylintFieldSet], OrderedSet[CoarsenedTarget]],
    ] = defaultdict(lambda: (OrderedSet(), OrderedSet()))
    for root in request.field_sets:
        ct = coarsened_targets_by_address[root.address]
        # NB: If there is a cycle in the roots, we still only take the first resolve, as the other
        # members will be validated when the partition is actually built.
        resolve = ct.representative[PythonResolveField].normalized_value(python_setup)
        # NB: We need to consume the entire un-memoized closure here. See the method comment.
        interpreter_constraints = InterpreterConstraints.create_from_compatibility_fields(
            (
                *(
                    tgt[InterpreterConstraintsField]
                    for tgt in ct.closure()
                    if tgt.has_field(InterpreterConstraintsField)
                ),
                *first_party_plugins.interpreter_constraints_fields,
            ),
            python_setup,
        )
        roots, root_cts = resolve_and_interpreter_constraints_to_coarsened_targets[
            (resolve, interpreter_constraints)
        ]
        roots.add(root)
        root_cts.add(ct)

    return PylintPartitions(
        PylintPartition(
            FrozenOrderedSet(roots),
            FrozenOrderedSet(CoarsenedTargets(root_cts).closure()),
            resolve if len(python_setup.resolves) > 1 else None,
            interpreter_constraints,
        )
        for (resolve, interpreter_constraints), (roots, root_cts) in sorted(
            resolve_and_interpreter_constraints_to_coarsened_targets.items()
        )
    )


@rule(desc="Lint using Pylint", level=LogLevel.DEBUG)
async def pylint_lint(request: PylintRequest, pylint: Pylint) -> LintResults:
    if pylint.skip:
        return LintResults([], linter_name=request.name)

    partitions = await Get(PylintPartitions, PylintRequest, request)
    partitioned_results = await MultiGet(
        Get(LintResult, PylintPartition, partition) for partition in partitions
    )
    return LintResults(partitioned_results, linter_name=request.name)


def rules():
    return [
        *collect_rules(),
        UnionRule(LintTargetsRequest, PylintRequest),
        *pex_from_targets.rules(),
    ]
