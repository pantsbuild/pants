# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.backend.nfpm.field_sets import (
    NfpmApkPackageFieldSet,
    NfpmArchlinuxPackageFieldSet,
    NfpmDebPackageFieldSet,
    NfpmPackageFieldSet,
    NfpmRpmPackageFieldSet,
)
from pants.backend.nfpm.field_sets import rules as field_sets_rules
from pants.backend.nfpm.subsystem import NfpmSubsystem
from pants.backend.nfpm.util_rules.generate_config import (
    NfpmPackageConfigRequest,
    generate_nfpm_yaml,
)
from pants.backend.nfpm.util_rules.generate_config import rules as generate_config_rules
from pants.backend.nfpm.util_rules.sandbox import (
    NfpmContentSandboxRequest,
    populate_nfpm_content_sandbox,
)
from pants.backend.nfpm.util_rules.sandbox import rules as sandbox_rules
from pants.core.goals import package
from pants.core.goals.package import BuiltPackage, BuiltPackageArtifact
from pants.core.util_rules.external_tool import download_external_tool
from pants.engine.fs import CreateDigest, Directory, MergeDigests
from pants.engine.internals.native_engine import AddPrefix, RemovePrefix
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import create_digest, digest_to_snapshot, merge_digests, remove_prefix
from pants.engine.platform import Platform
from pants.engine.process import Process, execute_process_or_raise
from pants.engine.rules import collect_rules, implicitly, rule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class BuiltNfpmPackageArtifact(BuiltPackageArtifact):
    packager: str = ""

    @classmethod
    def create(cls, relpath: str, packager: str) -> BuiltNfpmPackageArtifact:
        return cls(
            relpath=relpath,
            packager=packager,
            extra_log_lines=(f"Built {packager} package with nFPM: {relpath}",),
        )


@dataclass(frozen=True)
class NfpmPackageRequest:
    field_set: NfpmPackageFieldSet


@rule(level=LogLevel.INFO)
async def package_nfpm_package(
    request: NfpmPackageRequest,
    nfpm_subsystem: NfpmSubsystem,
    platform: Platform,
) -> BuiltPackage:
    output_dir = "__out"

    field_set = request.field_set

    nfpm_content_sandbox = await populate_nfpm_content_sandbox(
        NfpmContentSandboxRequest(field_set), **implicitly()
    )

    nfpm_config, downloaded_tool, output_dir_digest = await concurrently(
        generate_nfpm_yaml(
            NfpmPackageConfigRequest(field_set, nfpm_content_sandbox.digest), **implicitly()
        ),
        download_external_tool(nfpm_subsystem.get_request(platform)),
        create_digest(CreateDigest([Directory(output_dir)])),
    )

    sandbox_digest = await merge_digests(
        MergeDigests(
            (
                nfpm_content_sandbox.digest,
                nfpm_config.digest,
                downloaded_tool.digest,
                output_dir_digest,
            )
        )
    )

    result = await execute_process_or_raise(
        **implicitly(
            Process(
                argv=(
                    downloaded_tool.exe,
                    "package",  # or "pkg" or "p"
                    # use default config file: nfpm.yaml
                    "--packager",  # or "-p"
                    field_set.packager,
                    "--target",  # or "-t"
                    output_dir,
                ),
                description=f"Creating {field_set.packager} package with nFPM: {field_set.address}",
                input_digest=sandbox_digest,
                output_directories=(output_dir,),
            )
        ),
    )

    # The final directory that should contain the package artifact.
    # The package artifact itself will use the conventional filename generated by nFPM.
    output_path = field_set.output_path.value_or_default(file_ending=None)

    stripped_digest = await remove_prefix(RemovePrefix(result.output_digest, output_dir))
    final_snapshot = await digest_to_snapshot(**implicitly(AddPrefix(stripped_digest, output_path)))

    # nFPM creates only 1 file (any signature gets embedded in the package file).
    assert len(final_snapshot.files) == 1
    conventional_file_name = final_snapshot.files[0]

    return BuiltPackage(
        final_snapshot.digest,
        artifacts=(BuiltNfpmPackageArtifact.create(conventional_file_name, field_set.packager),),
    )


@rule
async def package_nfpm_apk_package(field_set: NfpmApkPackageFieldSet) -> BuiltPackage:
    built_package: BuiltPackage = await package_nfpm_package(
        NfpmPackageRequest(field_set), **implicitly()
    )
    return built_package


@rule
async def package_nfpm_archlinux_package(field_set: NfpmArchlinuxPackageFieldSet) -> BuiltPackage:
    built_package: BuiltPackage = await package_nfpm_package(
        NfpmPackageRequest(field_set), **implicitly()
    )
    return built_package


@rule
async def package_nfpm_deb_package(field_set: NfpmDebPackageFieldSet) -> BuiltPackage:
    built_package: BuiltPackage = await package_nfpm_package(
        NfpmPackageRequest(field_set), **implicitly()
    )
    return built_package


@rule
async def package_nfpm_rpm_package(field_set: NfpmRpmPackageFieldSet) -> BuiltPackage:
    built_package: BuiltPackage = await package_nfpm_package(
        NfpmPackageRequest(field_set), **implicitly()
    )
    return built_package


def rules():
    return [
        *package.rules(),
        *field_sets_rules(),
        *generate_config_rules(),
        *sandbox_rules(),
        *collect_rules(),
    ]
