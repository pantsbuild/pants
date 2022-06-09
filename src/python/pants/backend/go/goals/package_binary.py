# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.go.target_types import (
    GoBinaryMainPackage,
    GoBinaryMainPackageField,
    GoBinaryMainPackageRequest,
)
from pants.backend.go.util_rules.build_pkg import BuiltGoPackage
from pants.backend.go.util_rules.build_pkg_target import BuildGoPackageTargetRequest
from pants.backend.go.util_rules.import_analysis import ImportConfig, ImportConfigRequest
from pants.backend.go.util_rules.link import LinkedGoBinary, LinkGoBinaryRequest
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.core.goals.run import RunFieldSet
from pants.engine.fs import AddPrefix, Digest, MergeDigests
from pants.engine.internals.selectors import Get
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule
from pants.util.logging import LogLevel


@dataclass(frozen=True)
class GoBinaryFieldSet(PackageFieldSet, RunFieldSet):
    required_fields = (GoBinaryMainPackageField,)

    main: GoBinaryMainPackageField
    output_path: OutputPathField


@rule(desc="Package Go binary", level=LogLevel.DEBUG)
async def package_go_binary(field_set: GoBinaryFieldSet) -> BuiltPackage:
    main_pkg = await Get(GoBinaryMainPackage, GoBinaryMainPackageRequest(field_set.main))
    built_package = await Get(
        BuiltGoPackage, BuildGoPackageTargetRequest(main_pkg.address, is_main=True)
    )
    main_pkg_a_file_path = built_package.import_paths_to_pkg_a_files["main"]
    import_config = await Get(
        ImportConfig, ImportConfigRequest(built_package.import_paths_to_pkg_a_files)
    )
    input_digest = await Get(Digest, MergeDigests([built_package.digest, import_config.digest]))

    output_filename = PurePath(field_set.output_path.value_or_default(file_ending=None))
    binary = await Get(
        LinkedGoBinary,
        LinkGoBinaryRequest(
            input_digest=input_digest,
            archives=(main_pkg_a_file_path,),
            import_config_path=import_config.CONFIG_PATH,
            output_filename=f"./{output_filename.name}",
            description=f"Link Go binary for {field_set.address}",
        ),
    )

    renamed_output_digest = await Get(Digest, AddPrefix(binary.digest, str(output_filename.parent)))

    artifact = BuiltPackageArtifact(relpath=str(output_filename))
    return BuiltPackage(renamed_output_digest, (artifact,))


def rules():
    return [*collect_rules(), UnionRule(PackageFieldSet, GoBinaryFieldSet)]
