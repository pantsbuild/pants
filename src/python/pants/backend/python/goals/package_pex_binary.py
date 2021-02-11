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
    PexUnzipField,
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
from pants.engine.target import Sources, TransitiveTargets, TransitiveTargetsRequest
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property

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
    unzip: PexUnzipField
    execution_mode: PexExecutionModeField
    include_tools: PexIncludeToolsField

    @memoized_property
    def _execution_mode(self) -> PexExecutionMode:
        if self.unzip.value is True:
            if self.execution_mode.value not in (None, PexExecutionMode.UNZIP.value):
                raise Exception(
                    f"The deprecated {PexUnzipField.alias} field is set to `True` but the "
                    f"{PexExecutionModeField.alias} field contradicts this by requesting"
                    f"`{self.execution_mode.value!r}`. Correct this by only specifying a value for "
                    f"one field or the other, preferring the {PexExecutionModeField.alias} field."
                )
            return PexExecutionMode.UNZIP
        return (
            PexExecutionMode.ZIPAPP
            if self.execution_mode.value is None
            else PexExecutionMode(self.execution_mode.value)
        )

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

    # If a zip app, check for files targets because these will not be loadable as expected.
    if field_set._execution_mode == PexExecutionMode.ZIPAPP:
        files_addresses = sorted(
            tgt.address.spec
            for tgt in transitive_targets.dependencies
            if tgt.has_field(FilesSources)
            or tgt.get(Sources).can_generate(FilesSources, union_membership)
        )
        if files_addresses:
            logger.warning(
                f"The pex_binary target {field_set.address} depends on the below files targets, "
                f"but it's packaged as a zip app, so you will likely not be able to open the files "
                f"like you'd expect.\n\nInstead, consider setting the field "
                f"`execution_mode='unzip' or `execution_mode='venv'` on {field_set.address} to be "
                f"able to use Python's filesystem API (e.g. `with open()`) like you'd expect."
                f"\n\nFiles targets dependencies: {files_addresses}"
            )

    output_filename = field_set.output_path.value_or_default(field_set.address, file_ending="pex")
    two_step_pex = await Get(
        TwoStepPex,
        TwoStepPexFromTargetsRequest(
            PexFromTargetsRequest(
                addresses=[field_set.address],
                internal_only=False,
                entry_point=resolved_entry_point.val,
                platforms=PexPlatforms.create_from_platforms_field(field_set.platforms),
                output_filename=output_filename,
                additional_args=field_set.generate_additional_args(pex_binary_defaults),
            )
        ),
    )
    return BuiltPackage(two_step_pex.pex.digest, (BuiltPackageArtifact(output_filename),))


def rules():
    return [*collect_rules(), UnionRule(PackageFieldSet, PexBinaryFieldSet)]
