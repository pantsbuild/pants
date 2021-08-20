# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.debian.target_types import (
    DebianSources,
    DebianInstallPrefix,
    DebianPackageDependencies,
)
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.engine.fs import CreateDigest, Digest
from pants.core.util_rules.system_binaries import BinaryPathRequest, BinaryPaths
from pants.core.util_rules.archive import TarBinary
from pants.engine.internals.selectors import Get
from pants.engine.process import Process, ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import HydrateSourcesRequest, HydratedSources
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class DebianPackageFieldSet(PackageFieldSet):
    required_fields = (DebianSources, DebianInstallPrefix, DebianPackageDependencies)

    sources_dir: DebianSources
    install_prefix: DebianInstallPrefix
    packages: DebianPackageDependencies
    output_path: OutputPathField


@rule(level=LogLevel.INFO)
async def package_debian_package(field_set: DebianPackageFieldSet,
                                 tar_binary_path: TarBinary) -> BuiltPackage:
    dpkg_deb_path = await Get(
        BinaryPaths,
        BinaryPathRequest(
            binary_name="dpkg-deb",
            search_path=["/usr/bin"],
        ),
    )
    if not dpkg_deb_path.first_path:
        raise OSError("Could not find the `dpkg-deb` program on search paths ")

    output_filename = field_set.output_path.value_or_default(

        file_ending="deb",
    )

    hydrated_sources = await Get(HydratedSources, HydrateSourcesRequest(field_set.sources_dir))

    result = await Get(
        ProcessResult,
        Process(
            argv=(
                dpkg_deb_path.first_path.path,
                "--build",
                # TODO: this needs to become the root directory name that we get from sources_dir
                "sample-debian-package",
            ),
            description="Create a Debian package from the produced packages.",
            input_digest=hydrated_sources.snapshot.digest,
            output_files=(output_filename,),
            env={"PATH": str(PurePath(tar_binary_path.path).parent)},
        ),
    )
    return BuiltPackage(result.output_digest, artifacts=(BuiltPackageArtifact(output_filename),))


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, DebianPackageFieldSet),
    ]
