# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.target_types import (
    PexAlwaysWriteCacheField,
    PexBinaryDefaults,
    PexEmitWarningsField,
    PexEntryPointField,
    PexExecutionMode,
    PexExecutionModeField,
    PexIgnoreErrorsField,
    PexIncludeToolsField,
    PexInheritPathField,
)
from pants.backend.python.target_types import PexPlatformsField as PythonPlatformsField
from pants.backend.python.target_types import (
    PexShebangField,
    PexZipSafeField,
    ResolvedPexEntryPoint,
    ResolvePexEntryPointRequest,
)
from pants.backend.python.util_rules.pex import PexPlatforms, TwoStepPex
from pants.backend.python.util_rules.pex_from_targets import (
    PexFromTargetsRequest,
    TwoStepPexFromTargetsRequest,
)
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.goals.run import RunFieldSet
from pants.core.target_types import FilesSources
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    TransitiveTargets,
    TransitiveTargetsRequest,
    targets_with_sources_types,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.docutil import bracketed_docs_url
from pants.util.logging import LogLevel

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PexBinaryFieldSet(PackageFieldSet, RunFieldSet):
    required_fields = (PexEntryPointField,)

    entry_point: PexEntryPointField

    output_path: OutputPathField
    always_write_cache: PexAlwaysWriteCacheField
    emit_warnings: PexEmitWarningsField
    ignore_errors: PexIgnoreErrorsField
    inherit_path: PexInheritPathField
    shebang: PexShebangField
    zip_safe: PexZipSafeField
    platforms: PythonPlatformsField
    execution_mode: PexExecutionModeField
    include_tools: PexIncludeToolsField

    @property
    def _execution_mode(self) -> PexExecutionMode:
        return PexExecutionMode(self.execution_mode.value)

    def generate_additional_args(self, pex_binary_defaults: PexBinaryDefaults) -> Tuple[str, ...]:
        args = []
        if self.always_write_cache.value is True:
            args.append("--always-write-cache")
        if self.emit_warnings.value_or_global_default(pex_binary_defaults) is False:
            args.append("--no-emit-warnings")
        if self.ignore_errors.value is True:
            args.append("--ignore-errors")
        if self.inherit_path.value is not None:
            args.append(f"--inherit-path={self.inherit_path.value}")
        if self.shebang.value is not None:
            args.append(f"--python-shebang={self.shebang.value}")
        if self.zip_safe.value is False:
            args.append("--not-zip-safe")
        if self._execution_mode is PexExecutionMode.UNZIP:
            args.append("--unzip")
        if self._execution_mode is PexExecutionMode.VENV:
            args.append("--venv")
        if self.include_tools.value is True:
            args.append("--include-tools")
        return tuple(args)


@rule(level=LogLevel.DEBUG)
async def package_pex_binary(
    field_set: PexBinaryFieldSet,
    pex_binary_defaults: PexBinaryDefaults,
    union_membership: UnionMembership,
) -> BuiltPackage:
    resolved_entry_point, transitive_targets = await MultiGet(
        Get(ResolvedPexEntryPoint, ResolvePexEntryPointRequest(field_set.entry_point)),
        Get(TransitiveTargets, TransitiveTargetsRequest([field_set.address])),
    )

    # Warn if users depend on `files` targets, which won't be included in the PEX and is a common
    # gotcha.
    files_tgts = targets_with_sources_types(
        [FilesSources], transitive_targets.dependencies, union_membership
    )
    if files_tgts:
        files_addresses = sorted(tgt.address.spec for tgt in files_tgts)
        logger.warning(
            f"The pex_binary target {field_set.address} transitively depends on the below files "
            "targets, but Pants will not include them in the PEX. Filesystem APIs like `open()` "
            "are not able to load files within the binary itself; instead, they read from the "
            "current working directory."
            "\n\nInstead, use `resources` targets or wrap this `pex_binary` in an `archive`. See "
            f"{bracketed_docs_url('resources')}."
            f"\n\nFiles targets dependencies: {files_addresses}"
        )

    output_filename = field_set.output_path.value_or_default(field_set.address, file_ending="pex")
    two_step_pex = await Get(
        TwoStepPex,
        TwoStepPexFromTargetsRequest(
            PexFromTargetsRequest(
                addresses=[field_set.address],
                internal_only=False,
                # TODO(John Sirois): Support ConsoleScript in PexBinary targets:
                #  https://github.com/pantsbuild/pants/issues/11619
                main=resolved_entry_point.val,
                platforms=PexPlatforms.create_from_platforms_field(field_set.platforms),
                output_filename=output_filename,
                additional_args=field_set.generate_additional_args(pex_binary_defaults),
            )
        ),
    )
    return BuiltPackage(two_step_pex.pex.digest, (BuiltPackageArtifact(output_filename),))


def rules():
    return [*collect_rules(), UnionRule(PackageFieldSet, PexBinaryFieldSet)]
