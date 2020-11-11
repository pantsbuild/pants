# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, List, Tuple

from pants.backend.python.lint.pylint.subsystem import Pylint
from pants.backend.python.target_types import (
    InterpreterConstraintsField,
    PythonInterpreterCompatibility,
    PythonRequirementsField,
    PythonSources,
)
from pants.backend.python.util_rules import pex_from_targets
from pants.backend.python.util_rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexProcess,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.backend.python.util_rules.python_sources import (
    PythonSourceFiles,
    PythonSourceFilesRequest,
    StrippedPythonSourceFiles,
)
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    Digest,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
)
from pants.engine.process import FallibleProcessResult
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSet,
    Target,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import UnionRule
from pants.python.python_setup import PythonSetup
from pants.util.logging import LogLevel
from pants.util.meta import frozen_after_init
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class PylintFieldSet(FieldSet):
    required_fields = (PythonSources,)

    sources: PythonSources
    dependencies: Dependencies


@dataclass(frozen=True)
class PylintTargetSetup:
    field_set: PylintFieldSet
    target_with_dependencies: Targets


@frozen_after_init
@dataclass(unsafe_hash=True)
class PylintPartition:
    field_sets: Tuple[PylintFieldSet, ...]
    targets_with_dependencies: Targets
    interpreter_constraints: PexInterpreterConstraints
    plugin_targets: Targets

    def __init__(
        self,
        target_setups: Iterable[PylintTargetSetup],
        interpreter_constraints: PexInterpreterConstraints,
        plugin_targets: Iterable[Target],
    ) -> None:
        field_sets = []
        targets_with_deps: List[Target] = []
        for target_setup in target_setups:
            field_sets.append(target_setup.field_set)
            targets_with_deps.extend(target_setup.target_with_dependencies)

        self.field_sets = tuple(field_sets)
        self.targets_with_dependencies = Targets(targets_with_deps)
        self.interpreter_constraints = interpreter_constraints
        self.plugin_targets = Targets(plugin_targets)


class PylintRequest(LintRequest):
    field_set_type = PylintFieldSet


def generate_args(*, source_files: SourceFiles, pylint: Pylint) -> Tuple[str, ...]:
    args = []
    if pylint.config is not None:
        args.append(f"--rcfile={pylint.config}")
    args.extend(pylint.args)
    args.extend(source_files.files)
    return tuple(args)


@rule(level=LogLevel.DEBUG)
async def pylint_lint_partition(partition: PylintPartition, pylint: Pylint) -> LintResult:
    requirements_pex_request = Get(
        Pex,
        PexFromTargetsRequest,
        PexFromTargetsRequest.for_requirements(
            (field_set.address for field_set in partition.field_sets),
            # NB: These constraints must be identical to the other PEXes. Otherwise, we risk using
            # a different version for the requirements than the other two PEXes, which can result
            # in a PEX runtime error about missing dependencies.
            hardcoded_interpreter_constraints=partition.interpreter_constraints,
            internal_only=True,
            direct_deps_only=True,
        ),
    )

    plugin_requirements = PexRequirements.create_from_requirement_fields(
        plugin_tgt[PythonRequirementsField]
        for plugin_tgt in partition.plugin_targets
        if plugin_tgt.has_field(PythonRequirementsField)
    )
    # Right now any Pylint transitive requirements will shadow corresponding user
    # requirements, which could lead to problems.
    pylint_pex_request = Get(
        Pex,
        PexRequest(
            output_filename="pylint.pex",
            internal_only=True,
            requirements=PexRequirements([*pylint.all_requirements, *plugin_requirements]),
            entry_point=pylint.entry_point,
            interpreter_constraints=partition.interpreter_constraints,
            # TODO(John Sirois): Support shading python binaries:
            #   https://github.com/pantsbuild/pants/issues/9206
            additional_args=("--pex-path", requirements_pex_request.input.output_filename),
        ),
    )

    config_digest_request = Get(
        Digest,
        PathGlobs(
            globs=[pylint.config] if pylint.config else [],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--pylint-config`",
        ),
    )

    prepare_plugin_sources_request = Get(
        StrippedPythonSourceFiles, PythonSourceFilesRequest(partition.plugin_targets)
    )
    prepare_python_sources_request = Get(
        PythonSourceFiles, PythonSourceFilesRequest(partition.targets_with_dependencies)
    )
    field_set_sources_request = Get(
        SourceFiles, SourceFilesRequest(field_set.sources for field_set in partition.field_sets)
    )

    (
        pylint_pex,
        requirements_pex,
        config_digest,
        prepared_plugin_sources,
        prepared_python_sources,
        field_set_sources,
    ) = await MultiGet(
        pylint_pex_request,
        requirements_pex_request,
        config_digest_request,
        prepare_plugin_sources_request,
        prepare_python_sources_request,
        field_set_sources_request,
    )

    prefixed_plugin_sources = (
        await Get(
            Digest,
            AddPrefix(prepared_plugin_sources.stripped_source_files.snapshot.digest, "__plugins"),
        )
        if pylint.source_plugins
        else EMPTY_DIGEST
    )

    pythonpath = list(prepared_python_sources.source_roots)
    if pylint.source_plugins:
        # NB: Pylint source plugins must be explicitly loaded via PEX_EXTRA_SYS_PATH. The value must
        # point to the plugin's directory, rather than to a parent's directory, because
        # `load-plugins` takes a module name rather than a path to the module; i.e. `plugin`, but
        # not `path.to.plugin`. (This means users must have specified the parent directory as a
        # source root.)
        pythonpath.append("__plugins")

    input_digest = await Get(
        Digest,
        MergeDigests(
            (
                pylint_pex.digest,
                requirements_pex.digest,
                config_digest,
                prefixed_plugin_sources,
                prepared_python_sources.source_files.snapshot.digest,
            )
        ),
    )

    result = await Get(
        FallibleProcessResult,
        PexProcess(
            pylint_pex,
            argv=generate_args(source_files=field_set_sources, pylint=pylint),
            input_digest=input_digest,
            extra_env={"PEX_EXTRA_SYS_PATH": ":".join(pythonpath)},
            description=f"Run Pylint on {pluralize(len(partition.field_sets), 'file')}.",
            level=LogLevel.DEBUG,
        ),
    )
    return LintResult.from_fallible_process_result(
        result, partition_description=str(sorted(str(c) for c in partition.interpreter_constraints))
    )


@rule(desc="Lint using Pylint", level=LogLevel.DEBUG)
async def pylint_lint(
    request: PylintRequest, pylint: Pylint, python_setup: PythonSetup
) -> LintResults:
    if pylint.skip:
        return LintResults([], linter_name="Pylint")

    plugin_target_addresses = await Get(Addresses, UnparsedAddressInputs, pylint.source_plugins)
    plugin_targets_request = Get(
        TransitiveTargets, TransitiveTargetsRequest(plugin_target_addresses)
    )
    linted_targets_request = Get(
        Targets, Addresses(field_set.address for field_set in request.field_sets)
    )
    plugin_targets, linted_targets = await MultiGet(plugin_targets_request, linted_targets_request)

    plugin_targets_compatibility_fields = tuple(
        PexInterpreterConstraints.resolve_conflicting_fields(
            plugin_tgt[PythonInterpreterCompatibility],
            plugin_tgt[InterpreterConstraintsField],
            plugin_tgt.address,
        )
        for plugin_tgt in plugin_targets.closure
        if plugin_tgt.has_fields([PythonInterpreterCompatibility, InterpreterConstraintsField])
    )

    # Pylint needs direct dependencies in the chroot to ensure that imports are valid. However, it
    # doesn't lint those direct dependencies nor does it care about transitive dependencies.
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
        interpreter_constraints = PexInterpreterConstraints.create_from_compatibility_fields(
            (
                *(
                    PexInterpreterConstraints.resolve_conflicting_fields(
                        tgt[PythonInterpreterCompatibility],
                        tgt[InterpreterConstraintsField],
                        tgt.address,
                    )
                    for tgt in [tgt, *dependencies]
                    if tgt.has_fields([PythonInterpreterCompatibility, InterpreterConstraintsField])
                ),
                *plugin_targets_compatibility_fields,
            ),
            python_setup,
        )
        interpreter_constraints_to_target_setup[interpreter_constraints].add(target_setup)

    partitions = (
        PylintPartition(
            tuple(sorted(target_setups, key=lambda tgt_setup: tgt_setup.field_set.address)),
            interpreter_constraints,
            Targets(plugin_targets.closure),
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
