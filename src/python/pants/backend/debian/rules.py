# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.backend.debian.target_types import (
    DebianControlFile,
    DebianInstallPrefix,
    DebianPackageDependencies,
)
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.engine.internals.selectors import Get
from pants.engine.process import BinaryPathRequest, BinaryPaths, Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class DebianPackageFieldSet(PackageFieldSet):
    required_fields = (DebianControlFile, DebianInstallPrefix, DebianPackageDependencies)

    control: DebianControlFile
    install_prefix: DebianInstallPrefix
    packages: DebianPackageDependencies
    output_path: OutputPathField


@rule(level=LogLevel.DEBUG)
async def package_debian_package(field_set: DebianPackageFieldSet) -> BuiltPackage:
    dpkg_deb_path = await Get(
        BinaryPaths,
        BinaryPathRequest(
            binary_name="touch",
            search_path=["/usr/bin"],
        ),
    )
    if not dpkg_deb_path.first_path:
        raise OSError("Could not find the `touch` program on search paths ")

    output_filename = field_set.output_path.value_or_default(file_ending="deb")

    # TODO(alexey): add Debian packaging logic
    result = await Get(
        ProcessResult,
        Process(
            argv=(
                "touch",
                output_filename,
            ),
            description="Create a Debian package from the produced packages.",
            output_files=(output_filename,),
        ),
    )
    return BuiltPackage(result.output_digest, artifacts=(BuiltPackageArtifact(output_filename),))


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, DebianPackageFieldSet),
    ]
