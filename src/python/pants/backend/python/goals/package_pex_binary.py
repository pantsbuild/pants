# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import itertools
import logging
import os
from collections.abc import Iterable
from dataclasses import dataclass

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
    PexScieField,
    PexScieHashAlgField,
    PexScieNameStyleField,
    PexSciePlatformField,
    PexScriptField,
    PexShBootField,
    PexShebangField,
    PexStripEnvField,
    PexVenvHermeticScripts,
    PexVenvSitePackagesCopies,
    ResolvePexEntryPointRequest,
    ScieNameStyle,
)
from pants.backend.python.target_types_rules import resolve_pex_entry_point
from pants.backend.python.util_rules.pex import create_pex, digest_complete_platforms
from pants.backend.python.util_rules.pex_from_targets import (
    PexFromTargetsRequest,
    create_pex_from_targets,
)
from pants.core.environments.target_types import EnvironmentField
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.goals.run import RunFieldSet, RunInSandboxBehavior
from pants.engine.platform import Platform
from pants.engine.rules import collect_rules, implicitly, rule
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
    complete_platforms: PexCompletePlatformsField
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

    scie: PexScieField
    scie_name_style: PexScieNameStyleField
    scie_platform: PexSciePlatformField
    scie_hash_alg: PexScieHashAlgField

    def builds_pex_and_scie(self) -> bool:
        return self.scie.value is not None

    @property
    def _execution_mode(self) -> PexExecutionMode:
        return PexExecutionMode(self.execution_mode.value)

    def generate_additional_args(self, pex_binary_defaults: PexBinaryDefaults) -> tuple[str, ...]:
        args = []
        if self.emit_warnings.value_or_global_default(pex_binary_defaults) is False:
            args.append("--no-emit-warnings")
        elif self.emit_warnings.value_or_global_default(pex_binary_defaults) is True:
            args.append("--emit-warnings")
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

    def generate_scie_args(
        self,
    ) -> tuple[str, ...]:
        args = []
        if self.scie.value is not None:
            args.append(f"--scie={self.scie.value}")
        if self.scie_name_style.value is not None:
            args.append(f"--scie-name-style={self.scie_name_style.value}")
        if self.scie_platform.value is not None:
            args.extend([f"--scie-platform={platform}" for platform in self.scie_platform.value])
        if self.scie_hash_alg.value is not None:
            args.append(f"--scie-hash-alg={self.scie_hash_alg.value}")

        return tuple(args)

    def output_pex_filename(self) -> str:
        return self.output_path.value_or_default(file_ending="pex")

    def scie_output_filenames(self) -> tuple[str] | None:
        if not self.builds_pex_and_scie():
            return None
        return _scie_output_filenames(
            self.output_path.value_or_default(file_ending=None),
            self.scie_name_style.value,
            self.scie_platform.value,
            self.scie_hash_alg.value,
        )

    def scie_output_directories(self) -> tuple[str] | None:
        if not self.builds_pex_and_scie():
            return None
        return _scie_output_directories(
            self.output_path.value_or_default(file_ending=None),
            self.scie_name_style.value,
            self.scie_platform.value,
        )


# Stand alone functions for ease of testing
def _current_scie_platform() -> str:
    # This is only a subset of the platforms that Pex can prodice
    # scies for.  While Pants can produce foreign platform scies, the
    # "current" platform can only be one Pants itself can run on.
    return Platform.create_for_localhost().replace("_", "-")


# TODO: NEED OT REPLACE ARM-->aarch


def _scie_output_filenames(
    no_suffix_output_path: str,
    scie_name_style: str,
    scie_platform: Iterable[str] | None,
    scie_hash_alg: str | None,
) -> tuple[str] | None:
    filenames = []

    if scie_name_style == ScieNameStyle.DYNAMIC:
        filenames = (no_suffix_output_path,)
    elif scie_name_style == ScieNameStyle.PLATFORM_PARENT_DIR:
        return None  # handed by output_directories
    elif scie_name_style == ScieNameStyle.PLATFORM_FILE_SUFFIX:
        if scie_platform:
            filenames = [no_suffix_output_path + f"-{platform}" for platform in scie_platform]
        else:
            filenames = [no_suffix_output_path + f"-{_current_scie_platform()}"]

    if scie_hash_alg is None:
        return tuple(filenames)
    else:
        return tuple(
            itertools.chain.from_iterable(
                [(fname, f"{fname}.{scie_hash_alg}") for fname in filenames]
            )
        )


def _scie_output_directories(
    no_suffix_output_path: str,
    scie_name_style: str,
    scie_platform: Iterable[str] | None,
) -> tuple[str] | None:
    if scie_name_style != ScieNameStyle.PLATFORM_PARENT_DIR:
        return None

    if scie_platform:
        return tuple(
            [
                os.path.join(os.path.dirname(no_suffix_output_path), platform)
                for platform in scie_platform
            ]
        )
    else:
        return os.path.join(os.path.dirname(no_suffix_output_path), _current_scie_platform())


def _scie_build_package_artifacts(field_set: PexBinaryFieldSet) -> tuple[BuiltPackageArtifact]:
    artifacts = []

    if field_set.scie_output_filenames():
        artifacts.extend(
            [
                BuiltPackageArtifact(scie_filename)
                for scie_filename in field_set.scie_output_filenames()
            ]
        )
    if field_set.scie_output_directories():
        artifacts.extend(
            [BuiltPackageArtifact(scie_dir) for scie_dir in field_set.scie_output_directories()]
        )
    return tuple(artifacts)


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
    resolved_entry_point = await resolve_pex_entry_point(
        ResolvePexEntryPointRequest(field_set.entry_point)
    )

    output_filename = field_set.output_pex_filename()

    complete_platforms = await digest_complete_platforms(field_set.complete_platforms)

    request = PexFromTargetsRequest(
        addresses=[field_set.address],
        internal_only=False,
        main=resolved_entry_point.val or field_set.script.value or field_set.executable.value,
        inject_args=field_set.args.value or [],
        inject_env=field_set.env.value or FrozenDict[str, str](),
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
async def built_package_for_pex_from_targets_request(
    field_set: PexBinaryFieldSet,
) -> BuiltPackage:
    pft_request = await package_pex_binary(field_set, **implicitly())

    if field_set.builds_pex_and_scie():
        field_set.scie_output_filenames()
        pex_request = dataclasses.replace(
            await create_pex_from_targets(**implicitly(pft_request.request)),
            additional_args=(*pft_request.request.additional_args, *field_set.generate_scie_args()),
            scie_output_files=field_set.scie_output_filenames(),
            scie_output_directories=field_set.scie_output_directories(),
        )
        artifacts = (
            BuiltPackageArtifact(
                pex_request.output_filename,
            ),
            *_scie_build_package_artifacts(field_set),
        )

    else:
        pex_request = await create_pex_from_targets(**implicitly(pft_request.request))
        artifacts = (
            BuiltPackageArtifact(
                pex_request.output_filename,
            ),
        )

    pex = await create_pex(**implicitly(pex_request))

    return BuiltPackage(pex.digest, artifacts)


def rules():
    return [*collect_rules(), UnionRule(PackageFieldSet, PexBinaryFieldSet)]
