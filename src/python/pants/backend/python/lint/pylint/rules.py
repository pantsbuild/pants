# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Tuple

from pants.backend.python.lint.pylint.subsystem import Pylint
from pants.backend.python.rules import download_pex_bin, importable_python_sources, pex
from pants.backend.python.rules.importable_python_sources import ImportablePythonSources
from pants.backend.python.rules.pex import (
    Pex,
    PexInterpreterConstraints,
    PexRequest,
    PexRequirements,
)
from pants.backend.python.subsystems import python_native_code, subprocess_environment
from pants.backend.python.subsystems.subprocess_environment import SubprocessEncodingEnvironment
from pants.backend.python.target_types import (
    PythonInterpreterCompatibility,
    PythonRequirementsField,
    PythonSources,
)
from pants.core.goals.lint import LintRequest, LintResult, LintResults
from pants.core.util_rules import determine_source_files, strip_source_roots
from pants.core.util_rules.determine_source_files import SourceFiles, SpecifiedSourceFilesRequest
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import EMPTY_DIGEST, AddPrefix, Digest, MergeDigests, PathGlobs, Snapshot
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import SubsystemRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSetWithOrigin,
    Target,
    Targets,
    TransitiveTargets,
)
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.util.meta import frozen_after_init
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class PylintFieldSet(FieldSetWithOrigin):
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
        self.field_sets = tuple(target_setup.field_set for target_setup in target_setups)
        self.targets_with_dependencies = Targets(
            itertools.chain.from_iterable(
                target_setup.target_with_dependencies for target_setup in target_setups
            )
        )
        self.interpreter_constraints = interpreter_constraints
        self.plugin_targets = Targets(plugin_targets)


class PylintRequest(LintRequest):
    field_set_type = PylintFieldSet


def generate_args(*, specified_source_files: SourceFiles, pylint: Pylint) -> Tuple[str, ...]:
    args = []
    if pylint.config is not None:
        args.append(f"--rcfile={pylint.config}")
    args.extend(pylint.args)
    args.extend(specified_source_files.files)
    return tuple(args)


@rule
async def pylint_lint_partition(
    partition: PylintPartition,
    pylint: Pylint,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
) -> LintResult:
    # We build one PEX with Pylint requirements and another with all direct 3rd-party dependencies.
    # Splitting this into two PEXes gives us finer-grained caching. We then merge via `--pex-path`.
    plugin_requirements = PexRequirements.create_from_requirement_fields(
        plugin_tgt[PythonRequirementsField]
        for plugin_tgt in partition.plugin_targets
        if plugin_tgt.has_field(PythonRequirementsField)
    )
    target_requirements = PexRequirements.create_from_requirement_fields(
        tgt[PythonRequirementsField]
        for tgt in partition.targets_with_dependencies
        if tgt.has_field(PythonRequirementsField)
    )
    pylint_pex_request = Get[Pex](
        PexRequest(
            output_filename="pylint.pex",
            requirements=PexRequirements([*pylint.get_requirement_specs(), *plugin_requirements]),
            interpreter_constraints=partition.interpreter_constraints,
            entry_point=pylint.get_entry_point(),
        )
    )
    requirements_pex_request = Get[Pex](
        PexRequest(
            output_filename="requirements.pex",
            requirements=target_requirements,
            interpreter_constraints=partition.interpreter_constraints,
        )
    )
    # TODO(John Sirois): Support shading python binaries:
    #   https://github.com/pantsbuild/pants/issues/9206
    # Right now any Pylint transitive requirements will shadow corresponding user
    # requirements, which could lead to problems.
    pylint_runner_pex_args = ["--pex-path", ":".join(["pylint.pex", "requirements.pex"])]
    if pylint.source_plugins:
        # NB: See below for why we set PYTHONPATH to load source plugins. This setting is necessary
        # for PEX to pick up the PYTHONPATH value.
        pylint_runner_pex_args.append("--inherit-path=fallback")
    pylint_runner_pex_request = Get[Pex](
        PexRequest(
            output_filename="pylint_runner.pex",
            entry_point=pylint.get_entry_point(),
            interpreter_constraints=partition.interpreter_constraints,
            additional_args=pylint_runner_pex_args,
        )
    )

    config_snapshot_request = Get[Snapshot](
        PathGlobs(
            globs=[pylint.config] if pylint.config else [],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--pylint-config`",
        )
    )

    prepare_plugin_sources_request = Get[ImportablePythonSources](Targets, partition.plugin_targets)
    prepare_python_sources_request = Get[ImportablePythonSources](
        Targets, partition.targets_with_dependencies
    )
    specified_source_files_request = Get[SourceFiles](
        SpecifiedSourceFilesRequest(
            ((field_set.sources, field_set.origin) for field_set in partition.field_sets),
            strip_source_roots=True,
        )
    )

    (
        pylint_pex,
        requirements_pex,
        pylint_runner_pex,
        config_snapshot,
        prepared_plugin_sources,
        prepared_python_sources,
        specified_source_files,
    ) = await MultiGet(
        pylint_pex_request,
        requirements_pex_request,
        pylint_runner_pex_request,
        config_snapshot_request,
        prepare_plugin_sources_request,
        prepare_python_sources_request,
        specified_source_files_request,
    )

    prefixed_plugin_sources = (
        await Get[Digest](AddPrefix(prepared_plugin_sources.snapshot.digest, "__plugins"))
        if pylint.source_plugins
        else EMPTY_DIGEST
    )

    input_digest = await Get[Digest](
        MergeDigests(
            (
                pylint_pex.digest,
                requirements_pex.digest,
                pylint_runner_pex.digest,
                config_snapshot.digest,
                prefixed_plugin_sources,
                prepared_python_sources.snapshot.digest,
            )
        ),
    )

    address_references = ", ".join(
        sorted(field_set.address.reference() for field_set in partition.field_sets)
    )

    process = pylint_runner_pex.create_process(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path="./pylint_runner.pex",
        # NB: Pylint source plugins must be explicitly loaded via PYTHONPATH. The value must
        # point to the plugin's directory, rather than to a parent's directory, because
        # `load-plugins` takes a module name rather than a path to the module; i.e. `plugin`, but
        # not `path.to.plugin`. (This means users must have specified the parent directory as a
        # source root.)
        env={"PYTHONPATH": "./__plugins"} if pylint.source_plugins else None,
        pex_args=generate_args(specified_source_files=specified_source_files, pylint=pylint),
        input_digest=input_digest,
        description=(
            f"Run Pylint on {pluralize(len(partition.field_sets), 'target')}: {address_references}."
        ),
    )
    result = await Get[FallibleProcessResult](Process, process)
    return LintResult.from_fallible_process_result(result, linter_name="Pylint")


@rule(desc="Lint using Pylint")
async def pylint_lint(
    request: PylintRequest, pylint: Pylint, python_setup: PythonSetup
) -> LintResults:
    if pylint.skip:
        return LintResults()

    plugin_targets_request = Get[TransitiveTargets](
        Addresses(Address.parse(plugin_addr) for plugin_addr in pylint.source_plugins)
    )
    linted_targets_request = Get[Targets](
        Addresses(field_set.address for field_set in request.field_sets)
    )
    plugin_targets, linted_targets = await MultiGet(plugin_targets_request, linted_targets_request)

    plugin_targets_compatibility_fields = tuple(
        plugin_tgt[PythonInterpreterCompatibility]
        for plugin_tgt in plugin_targets.closure
        if plugin_tgt.has_field(PythonInterpreterCompatibility)
    )

    # Pylint needs direct dependencies in the chroot to ensure that imports are valid. However, it
    # doesn't lint those direct dependencies nor does it care about transitive dependencies.
    per_target_dependencies = await MultiGet(
        Get[Targets](DependenciesRequest(field_set.dependencies))
        for field_set in request.field_sets
    )

    # We batch targets by their interpreter constraints to ensure, for example, that all Python 2
    # targets run together and all Python 3 targets run together.
    interpreter_constraints_to_target_setup = defaultdict(set)
    for field_set, tgt, dependencies in zip(
        request.field_sets, linted_targets, per_target_dependencies
    ):
        target_setup = PylintTargetSetup(field_set, Targets([tgt, *dependencies]))
        interpreter_constraints = PexInterpreterConstraints.create_from_compatibility_fields(
            (
                *(tgt.get(PythonInterpreterCompatibility) for tgt in [tgt, *dependencies]),
                *plugin_targets_compatibility_fields,
            ),
            python_setup,
        ) or PexInterpreterConstraints(pylint.default_interpreter_constraints)
        interpreter_constraints_to_target_setup[interpreter_constraints].add(target_setup)

    partitions = (
        PylintPartition(
            tuple(sorted(target_setups, key=lambda target_setup: target_setup.field_set.address)),
            interpreter_constraints,
            Targets(plugin_targets.closure),
        )
        for interpreter_constraints, target_setups in sorted(
            interpreter_constraints_to_target_setup.items()
        )
    )
    partitioned_results = await MultiGet(
        Get[LintResult](PylintPartition, partition) for partition in partitions
    )
    return LintResults(partitioned_results)


def rules():
    return [
        pylint_lint,
        pylint_lint_partition,
        SubsystemRule(Pylint),
        UnionRule(LintRequest, PylintRequest),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *importable_python_sources.rules(),
        *strip_source_roots.rules(),
        *python_native_code.rules(),
        *subprocess_environment.rules(),
    ]
