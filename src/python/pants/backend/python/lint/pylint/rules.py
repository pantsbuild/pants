# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple, cast

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
from pants.core.goals.lint import LinterFieldSet, LinterFieldSets, LintResult
from pants.core.util_rules import determine_source_files, strip_source_roots
from pants.core.util_rules.determine_source_files import SourceFiles, SpecifiedSourceFilesRequest
from pants.engine.addresses import Address, Addresses
from pants.engine.fs import Digest, MergeDigests, PathGlobs, Snapshot
from pants.engine.process import FallibleProcessResult, Process
from pants.engine.rules import SubsystemRule, named_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Dependencies, Targets, TransitiveTargets
from pants.engine.unions import UnionRule
from pants.option.global_options import GlobalOptions, GlobMatchErrorBehavior
from pants.python.python_setup import PythonSetup
from pants.util.strutil import pluralize


@dataclass(frozen=True)
class PylintFieldSet(LinterFieldSet):
    required_fields = (PythonSources,)

    sources: PythonSources
    dependencies: Dependencies
    compatibility: PythonInterpreterCompatibility


class PylintFieldSets(LinterFieldSets):
    field_set_type = PylintFieldSet


def generate_args(*, specified_source_files: SourceFiles, pylint: Pylint) -> Tuple[str, ...]:
    args = []
    if pylint.config is not None:
        args.append(f"--rcfile={pylint.config}")
    args.extend(pylint.args)
    args.extend(specified_source_files.files)
    return tuple(args)


@named_rule(desc="Lint using Pylint")
async def pylint_lint(
    field_sets: PylintFieldSets,
    pylint: Pylint,
    python_setup: PythonSetup,
    subprocess_encoding_environment: SubprocessEncodingEnvironment,
    global_options: GlobalOptions,
) -> LintResult:
    if pylint.skip:
        return LintResult.noop()

    if pylint.source_plugins and not pylint.config:
        raise ValueError(
            "You specified `--pylint-source-plugins` but did not specify `--pylint-config`. Please "
            "create a pylintrc config file and configure `init-hook` and `load-plugins`. Run "
            f"`{global_options.options.pants_bin_name} target-types "
            "--details=pylint_source_plugin` for instructions."
        )

    plugin_targets_request = Get[TransitiveTargets](
        Addresses(Address.parse(plugin_addr) for plugin_addr in pylint.source_plugins)
    )

    # Pylint needs direct dependencies in the chroot to ensure that imports are valid. However, it
    # doesn't lint those direct dependencies nor does it care about transitive dependencies.
    addresses_with_dependencies = []
    for field_set in field_sets:
        addresses_with_dependencies.append(field_set.address)
        addresses_with_dependencies.extend(field_set.dependencies.value or ())
    targets_with_dependencies_request = Get[Targets](Addresses(addresses_with_dependencies))

    plugin_targets, targets_with_dependencies = cast(
        Tuple[TransitiveTargets, Targets],
        await MultiGet([plugin_targets_request, targets_with_dependencies_request]),
    )
    targets = Targets((*plugin_targets.closure, *targets_with_dependencies))

    # NB: Pylint output depends upon which Python interpreter version it's run with. See
    # http://pylint.pycqa.org/en/latest/faq.html#what-versions-of-python-is-pylint-supporting.
    interpreter_constraints = PexInterpreterConstraints.create_from_compatibility_fields(
        (
            *(field_set.compatibility for field_set in field_sets),
            *(
                plugin_tgt[PythonInterpreterCompatibility]
                for plugin_tgt in plugin_targets.closure
                if plugin_tgt.has_field(PythonInterpreterCompatibility)
            ),
        ),
        python_setup,
    )

    # We build one PEX with Pylint requirements and another with all direct 3rd-party dependencies.
    # Splitting this into two PEXes gives us finer-grained caching. We then merge via `--pex-path`.
    pylint_pex_request = Get[Pex](
        PexRequest(
            output_filename="pylint.pex",
            requirements=PexRequirements(
                [
                    *pylint.get_requirement_specs(),
                    *PexRequirements.create_from_requirement_fields(
                        plugin_tgt[PythonRequirementsField]
                        for plugin_tgt in plugin_targets.closure
                        if plugin_tgt.has_field(PythonRequirementsField)
                    ),
                ]
            ),
            interpreter_constraints=interpreter_constraints,
            entry_point=pylint.get_entry_point(),
        )
    )
    requirements_pex_request = Get[Pex](
        PexRequest(
            output_filename="requirements.pex",
            requirements=PexRequirements.create_from_requirement_fields(
                tgt[PythonRequirementsField]
                for tgt in targets_with_dependencies
                if tgt.has_field(PythonRequirementsField)
            ),
            interpreter_constraints=interpreter_constraints,
        )
    )
    pylint_runner_pex_request = Get[Pex](
        PexRequest(
            output_filename="pylint_runner.pex",
            entry_point=pylint.get_entry_point(),
            interpreter_constraints=interpreter_constraints,
            additional_args=(
                "--pex-path",
                # TODO(John Sirois): Support shading python binaries:
                #   https://github.com/pantsbuild/pants/issues/9206
                # Right now any Pylint transitive requirements will shadow corresponding user
                # requirements which could lead to problems.
                ":".join(["pylint.pex", "requirements.pex"]),
            ),
        )
    )

    config_snapshot_request = Get[Snapshot](
        PathGlobs(
            globs=[pylint.config] if pylint.config else [],
            glob_match_error_behavior=GlobMatchErrorBehavior.error,
            description_of_origin="the option `--pylint-config`",
        )
    )

    prepare_python_sources_request = Get[ImportablePythonSources](Targets, targets)
    specified_source_files_request = Get[SourceFiles](
        SpecifiedSourceFilesRequest(
            ((field_set.sources, field_set.origin) for field_set in field_sets),
            strip_source_roots=True,
        )
    )

    (
        pylint_pex,
        requirements_pex,
        pylint_runner_pex,
        config_snapshot,
        prepared_python_sources,
        specified_source_files,
    ) = cast(
        Tuple[Pex, Pex, Pex, Snapshot, ImportablePythonSources, SourceFiles],
        await MultiGet(
            [
                pylint_pex_request,
                requirements_pex_request,
                pylint_runner_pex_request,
                config_snapshot_request,
                prepare_python_sources_request,
                specified_source_files_request,
            ]
        ),
    )

    input_digest = await Get[Digest](
        MergeDigests(
            (
                pylint_pex.digest,
                requirements_pex.digest,
                pylint_runner_pex.digest,
                config_snapshot.digest,
                prepared_python_sources.snapshot.digest,
            )
        ),
    )

    address_references = ", ".join(
        sorted(field_set.address.reference() for field_set in field_sets)
    )

    process = requirements_pex.create_process(
        python_setup=python_setup,
        subprocess_encoding_environment=subprocess_encoding_environment,
        pex_path=f"./pylint_runner.pex",
        pex_args=generate_args(specified_source_files=specified_source_files, pylint=pylint),
        input_digest=input_digest,
        description=f"Run Pylint on {pluralize(len(field_sets), 'target')}: {address_references}.",
    )
    result = await Get[FallibleProcessResult](Process, process)
    return LintResult.from_fallible_process_result(result, linter_name="Pylint")


def rules():
    return [
        pylint_lint,
        SubsystemRule(Pylint),
        UnionRule(LinterFieldSets, PylintFieldSets),
        *download_pex_bin.rules(),
        *determine_source_files.rules(),
        *pex.rules(),
        *importable_python_sources.rules(),
        *strip_source_roots.rules(),
        *python_native_code.rules(),
        *subprocess_environment.rules(),
    ]
