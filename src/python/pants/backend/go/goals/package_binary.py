# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.go.target_types import GoBinaryMainAddress
from pants.backend.go.util_rules.build_go_pkg import BuildGoPackageRequest, BuiltGoPackage
from pants.backend.go.util_rules.go_pkg import (
    is_first_party_package_target,
    is_third_party_package_target,
)
from pants.backend.go.util_rules.import_analysis import GatheredImports, GatherImportsRequest
from pants.backend.go.util_rules.sdk import GoSdkProcess
from pants.build_graph.address import Address, AddressInput
from pants.core.goals.package import (
    BuiltPackage,
    BuiltPackageArtifact,
    OutputPathField,
    PackageFieldSet,
)
from pants.engine.fs import AddPrefix, Digest, MergeDigests
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.process import ProcessResult
from pants.engine.rules import collect_rules, rule
from pants.engine.target import TransitiveTargets, TransitiveTargetsRequest, WrappedTarget
from pants.engine.unions import UnionRule
from pants.util.ordered_set import FrozenOrderedSet


@dataclass(frozen=True)
class GoBinaryFieldSet(PackageFieldSet):
    required_fields = (GoBinaryMainAddress,)

    main_address: GoBinaryMainAddress
    output_path: OutputPathField


@rule
async def package_go_binary(
    field_set: GoBinaryFieldSet,
) -> BuiltPackage:
    main_address = field_set.main_address.value or ""
    main_go_package_address = await Get(
        Address,
        AddressInput,
        AddressInput.parse(main_address, relative_to=field_set.address.spec_path),
    )
    wrapped_main_go_package_target = await Get(WrappedTarget, Address, main_go_package_address)
    main_go_package_target = wrapped_main_go_package_target.target
    built_main_go_package = await Get(
        BuiltGoPackage, BuildGoPackageRequest(address=main_go_package_target.address, is_main=True)
    )

    transitive_targets = await Get(
        TransitiveTargets, TransitiveTargetsRequest(roots=[main_go_package_target.address])
    )
    buildable_deps = [
        tgt
        for tgt in transitive_targets.dependencies
        if is_first_party_package_target(tgt) or is_third_party_package_target(tgt)
    ]

    built_transitive_go_deps_requests = [
        Get(BuiltGoPackage, BuildGoPackageRequest(address=tgt.address)) for tgt in buildable_deps
    ]
    built_transitive_go_deps = await MultiGet(built_transitive_go_deps_requests)

    gathered_imports = await Get(
        GatheredImports,
        GatherImportsRequest(
            packages=FrozenOrderedSet(built_transitive_go_deps),
            include_stdlib=True,
        ),
    )

    input_digest = await Get(
        Digest, MergeDigests([gathered_imports.digest, built_main_go_package.object_digest])
    )

    output_filename = PurePath(field_set.output_path.value_or_default(file_ending=None))
    result = await Get(
        ProcessResult,
        GoSdkProcess(
            input_digest=input_digest,
            command=(
                "tool",
                "link",
                "-importcfg",
                "./importcfg",
                "-o",
                f"./{output_filename.name}",
                "-buildmode=exe",  # seen in `go build -x` output
                "./__pkg__.a",
            ),
            description="Link Go binary.",
            output_files=(f"./{output_filename.name}",),
        ),
    )

    renamed_output_digest = await Get(
        Digest, AddPrefix(result.output_digest, str(output_filename.parent))
    )

    artifact = BuiltPackageArtifact(relpath=str(output_filename))
    return BuiltPackage(digest=renamed_output_digest, artifacts=(artifact,))


def rules():
    return [
        *collect_rules(),
        UnionRule(PackageFieldSet, GoBinaryFieldSet),
    ]
