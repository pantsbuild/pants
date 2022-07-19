# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from typing import Tuple

from pants.backend.python.target_types import (
    PexBinaryDefaults,
    PexCompletePlatformsField,
    PexEmitWarningsField,
    PexEntryPointField,
    PexExecutionMode,
    PexExecutionModeField,
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
    PexShebangField,
    PexStripEnvField,
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
from pants.core.goals.run import RunFieldSet
from pants.core.target_types import FileSourceField
from pants.engine.rules import Get, MultiGet, collect_rules, rule
from pants.engine.target import (
    TransitiveTargets,
    TransitiveTargetsRequest,
    targets_with_sources_types,
)
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.docutil import doc_url
from pants.util.logging import LogLevel
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PexBinaryFieldSet(PackageFieldSet, RunFieldSet):
    required_fields = (PexEntryPointField,)

    entry_point: PexEntryPointField
    script: PexScriptField

    output_path: OutputPathField
    emit_warnings: PexEmitWarningsField
    ignore_errors: PexIgnoreErrorsField
    inherit_path: PexInheritPathField
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

    @property
    def _execution_mode(self) -> PexExecutionMode:
        return PexExecutionMode(self.execution_mode.value)

    def generate_additional_args(self, pex_binary_defaults: PexBinaryDefaults) -> Tuple[str, ...]:
        args = []
        if self.emit_warnings.value_or_global_default(pex_binary_defaults) is False:
            args.append("--no-emit-warnings")
        if self.resolve_local_platforms.value_or_global_default(pex_binary_defaults) is True:
            args.append("--resolve-local-platforms")
        if self.ignore_errors.value is True:
            args.append("--ignore-errors")
        if self.inherit_path.value is not None:
            args.append(f"--inherit-path={self.inherit_path.value}")
        if self.shebang.value is not None:
            args.append(f"--python-shebang={self.shebang.value}")
        if self.strip_env.value is False:
            args.append("--no-strip-pex-env")
        if self._execution_mode is PexExecutionMode.VENV:
            args.extend(("--venv", "prepend"))
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
    file_tgts = targets_with_sources_types(
        [FileSourceField], transitive_targets.dependencies, union_membership
    )
    if file_tgts:
        files_addresses = sorted(tgt.address.spec for tgt in file_tgts)
        logger.warning(
            softwrap(
                f"""
                The `pex_binary` target {field_set.address} transitively depends on the below `files`
                targets, but Pants will not include them in the PEX. Filesystem APIs like `open()`
                are not able to load files within the binary itself; instead, they read from the
                current working directory.

                Instead, use `resources` targets or wrap this `pex_binary` in an `archive`.
                See {doc_url('resources')}.

                Files targets dependencies: {files_addresses}
                """
            )
        )

    output_filename = field_set.output_path.value_or_default(file_ending="pex")

    complete_platforms = await Get(
        CompletePlatforms, PexCompletePlatformsField, field_set.complete_platforms
    )

    pex = await Get(
        Pex,
        PexFromTargetsRequest(
            addresses=[field_set.address],
            internal_only=False,
            main=resolved_entry_point.val or field_set.script.value,
            platforms=PexPlatforms.create_from_platforms_field(field_set.platforms),
            complete_platforms=complete_platforms,
            output_filename=output_filename,
            layout=PexLayout(field_set.layout.value),
            additional_args=field_set.generate_additional_args(pex_binary_defaults),
            include_requirements=field_set.include_requirements.value,
            include_source_files=field_set.include_sources.value,
            include_local_dists=True,
        ),
    )
    return BuiltPackage(pex.digest, (BuiltPackageArtifact(output_filename),))


def rules():
    return [*collect_rules(), UnionRule(PackageFieldSet, PexBinaryFieldSet)]
