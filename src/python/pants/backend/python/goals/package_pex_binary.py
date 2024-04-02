# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.target_types import (
    PexArgsField,
    PexBinaryDefaults,
    PexCheckField,
    PexCompletePlatformsField,
    PexEmitWarningsField,
    PexEntryPointField,
    PexEnvField,
    PexExecutableField,
    PexExecutionMode,
    PexExecutionModeField,
    PexExtraBuildArgsField,
    PexIgnoreErrorsField,
    PexIncludeRequirementsField,
    PexIncludeSourcesField,
    PexIncludeToolsField,
    PexInheritPathField,
    PexLayout,
    PexLayoutField,
    PexPlatformsField,
    PexResolveLocalPlatformsField,
    PexScriptField,
    PexShBootField,
    PexShebangField,
    PexStripEnvField,
    PexVenvHermeticScripts,
    PexVenvSitePackagesCopies,
    ResolvedPexEntryPoint,
    ResolvePexEntryPointRequest,
)
from pants.backend.python.util_rules.pex import CompletePlatforms, Pex, PexPlatforms
from pants.backend.python.util_rules.pex_from_targets import PexFromTargetsRequest
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior
from pants.core.util_rules.environments import EnvironmentField
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PexBinaryFieldSet(PackageFieldSet, RunFieldSet):
    run_in_sandbox_behavior = RunInSandboxBehavior.RUN_REQUEST_HERMETIC

    required_fields = (PexEntryPointField,)

    entry_point: PexEntryPointField
    script: PexScriptField
    executable: PexExecutableField
    args: PexArgsField
    env: PexEnvField

    output_path: OutputPathField
    emit_warnings: PexEmitWarningsField
    ignore_errors: PexIgnoreErrorsField
    inherit_path: PexInheritPathField
    sh_boot: PexShBootField
    shebang: PexShebangField
    strip_env: PexStripEnvField
    platforms: PexPlatformsField
    complete_platforms: PexCompletePlatformsField
    resolve_local_platforms: PexResolveLocalPlatformsField
    layout: PexLayoutField
    execution_mode: PexExecutionModeField
    include_requirements: PexIncludeRequirementsField
    include_sources: PexIncludeSourcesField
    include_tools: PexIncludeToolsField
    venv_site_packages_copies: PexVenvSitePackagesCopies
    venv_hermetic_scripts: PexVenvHermeticScripts
    environment: EnvironmentField
    check: PexCheckField
    extra_build_args: PexExtraBuildArgsField

    @property
    def _execution_mode(self) -> PexExecutionMode:
        return PexExecutionMode(self.execution_mode.value)

    def generate_additional_args(self, pex_binary_defaults: PexBinaryDefaults) -> Tuple[str, ...]:
        args = []
        if self.emit_warnings.value_or_global_default(pex_binary_defaults) is False:
            args.append("--no-emit-warnings")
        elif self.emit_warnings.value_or_global_default(pex_binary_defaults) is True:
            args.append("--emit-warnings")
        if self.resolve_local_platforms.value_or_global_default(pex_binary_defaults) is True:
            args.append("--resolve-local-platforms")
        if self.ignore_errors.value is True:
            args.append("--ignore-errors")
        if self.inherit_path.value is not None:
            args.append(f"--inherit-path={self.inherit_path.value}")
        if self.sh_boot.value is True:
            args.append("--sh-boot")
        if self.check.value is not None:
            args.append(f"--check={self.check.value}")
        if self.shebang.value is not None:
            args.append(f"--python-shebang={self.shebang.value}")
        if self.strip_env.value is False:
            args.append("--no-strip-pex-env")
        if self._execution_mode is PexExecutionMode.VENV:
            args.extend(("--venv", "prepend"))
        if self.include_tools.value is True:
            args.append("--include-tools")
        if self.venv_site_packages_copies.value is True:
            args.append("--venv-site-packages-copies")
        if self.venv_hermetic_scripts.value is False:
            args.append("--non-hermetic-venv-scripts")
        if self.extra_build_args.value:
            args.extend(self.extra_build_args.value)
        return tuple(args)


@dataclass(frozen=True)
class PexFromTargetsRequestForBuiltPackage:
    """An intermediate class that gives consumers access to the data used to create a
    `PexFromTargetsRequest` to fulfil a `BuiltPackage` request.

    This class is used directly by `run_pex_binary`, but should be handled transparently by direct
    `BuiltPackage` requests.
    """

    request: PexFromTargetsRequest


@rule(level=LogLevel.DEBUG)
async def package_pex_binary(
    field_set: PexBinaryFieldSet,
    pex_binary_defaults: PexBinaryDefaults,
) -> PexFromTargetsRequestForBuiltPackage:
    resolved_entry_point = await Get(
        ResolvedPexEntryPoint, ResolvePexEntryPointRequest(field_set.entry_point)
    )

    output_filename = field_set.output_path.value_or_default(file_ending="pex")

    complete_platforms = await Get(
        CompletePlatforms, PexCompletePlatformsField, field_set.complete_platforms
    )

    request = PexFromTargetsRequest(
        addresses=[field_set.address],
        internal_only=False,
        main=resolved_entry_point.val or field_set.script.value or field_set.executable.value,
        inject_args=field_set.args.value or [],
        inject_env=field_set.env.value or FrozenDict[str, str](),
        platforms=PexPlatforms.create_from_platforms_field(field_set.platforms),
        complete_platforms=complete_platforms,
        output_filename=output_filename,
        layout=PexLayout(field_set.layout.value),
        additional_args=field_set.generate_additional_args(pex_binary_defaults),
        include_requirements=field_set.include_requirements.value,
        include_source_files=field_set.include_sources.value,
        include_local_dists=True,
        warn_for_transitive_files_targets=True,
    )

    return PexFromTargetsRequestForBuiltPackage(request)


@rule
async def built_pacakge_for_pex_from_targets_request(
    request: PexFromTargetsRequestForBuiltPackage,
) -> BuiltPackage:
    pft_request = request.request
    pex = await Get(Pex, PexFromTargetsRequest, pft_request)
    return BuiltPackage(pex.digest, (BuiltPackageArtifact(pft_request.output_filename),))


def rules():
    return [*collect_rules(), UnionRule(PackageFieldSet, PexBinaryFieldSet)]
