# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable

from pants.backend.debian.target_types import (
    DebianInstallPrefix,
    DebianPackageDependencies,
    DebianSources,
)
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.util_rules.system_binaries import BinaryPathRequest, TarBinary
from pants.engine.fs import CreateDigest, FileEntry
from pants.engine.process import Process
from pants.engine.rules import Rule, collect_rules, rule, implicitly
from pants.core.util_rules.system_binaries import find_binary
from pants.engine.internals.graph import hydrate_sources
from pants.engine.process import fallible_to_exec_result_or_raise
from pants.engine.intrinsics import directory_digest_to_digest_entries
from pants.engine.intrinsics import create_digest_to_digest
from pants.engine.target import HydrateSourcesRequest
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
async def package_debian_package(
    field_set: DebianPackageFieldSet, tar_binary_path: TarBinary
) -> BuiltPackage:
    dpkg_deb_path = await find_binary(BinaryPathRequest(
            binary_name="dpkg-deb",
            search_path=["/usr/bin"],
        ), **implicitly())
    if not dpkg_deb_path.first_path:
        raise OSError(f"Could not find the `{dpkg_deb_path.binary_name}` program in `/usr/bin`.")

    hydrated_sources = await hydrate_sources(HydrateSourcesRequest(field_set.sources_dir), **implicitly())

    # Since all the sources are coming only from a single directory, it is
    # safe to pick an arbitrary file and get its root directory name.
    # Validation of the resolved files has been called on the target, so it is known that
    # snapshot.files isn't empty.
    sources_directory_name = PurePath(hydrated_sources.snapshot.files[0]).parts[0]

    result = await fallible_to_exec_result_or_raise(
        **implicitly(
            Process(
                argv=(
                    dpkg_deb_path.first_path.path,
                    "--build",
                    sources_directory_name,
                ),
                description="Create a Debian package from the produced packages.",
                input_digest=hydrated_sources.snapshot.digest,
                # dpkg-deb produces a file with the same name as the input directory
                output_files=(f"{sources_directory_name}.deb",),
                env={"PATH": str(PurePath(tar_binary_path.path).parent)},
            )
        )
    )
    # The output Debian package file needs to be renamed to match the output_path field.
    output_filename = field_set.output_path.value_or_default(
        file_ending="deb",
    )
    digest_entries = await directory_digest_to_digest_entries(result.output_digest)
    assert len(digest_entries) == 1
    result_file_entry = digest_entries[0]
    assert isinstance(result_file_entry, FileEntry)
    new_file = FileEntry(output_filename, result_file_entry.file_digest)

    final_result = await create_digest_to_digest(CreateDigest([new_file]))
    return BuiltPackage(final_result, artifacts=(BuiltPackageArtifact(output_filename),))


def rules() -> Iterable[Rule | UnionRule]:
    return (
        *collect_rules(),
        UnionRule(PackageFieldSet, DebianPackageFieldSet),
    )
