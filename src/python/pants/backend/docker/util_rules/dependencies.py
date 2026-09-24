# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.docker.subsystems.dockerfile_parser import (
    DockerfileInfoRequest,
    parse_dockerfile,
)
from pants.backend.docker.target_types import DockerImageDependenciesField
from pants.backend.docker.util_rules.docker_build_args import (
    DockerBuildArgsRequest,
    docker_build_args,
)
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.base.specs import FileLiteralSpec, RawSpecs
from pants.core.goals.package import AllPackageableTargets, OutputPathField
from pants.engine.addresses import Address, Addresses, UnparsedAddressInputs
from pants.engine.internals.graph import resolve_targets, resolve_unparsed_address_inputs
from pants.engine.rules import collect_rules, concurrently, implicitly, rule
from pants.engine.target import FieldSet, InferDependenciesRequest, InferredDependencies
from pants.engine.unions import UnionRule
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class DockerInferenceFieldSet(FieldSet):
    required_fields = (DockerImageDependenciesField,)

    dependencies: DockerImageDependenciesField


@dataclass(frozen=True)
class PackageableOutputPathsRequest:
    file_ending: str | None


@dataclass(frozen=True)
class PackageableOutputPaths:
    """Maps each default output path (for one file ending) to the positions in
    `AllPackageableTargets` of the targets which produce it."""

    positions_by_path: FrozenDict[str, tuple[int, ...]]


@dataclass(frozen=True)
class PackageableTargetPositions:
    positions: FrozenDict[Address, int]


@rule
async def packageable_target_positions(
    all_packageable_targets: AllPackageableTargets,
) -> PackageableTargetPositions:
    return PackageableTargetPositions(
        FrozenDict({target.address: i for i, target in enumerate(all_packageable_targets)})
    )


@rule
async def packageable_output_paths(
    request: PackageableOutputPathsRequest, all_packageable_targets: AllPackageableTargets
) -> PackageableOutputPaths:
    positions_by_path: dict[str, list[int]] = defaultdict(list)
    for i, target in enumerate(all_packageable_targets):
        output_path = target.get(OutputPathField).value_or_default(file_ending=request.file_ending)
        positions_by_path[output_path].append(i)
    return PackageableOutputPaths(
        FrozenDict({path: tuple(positions) for path, positions in positions_by_path.items()})
    )


class InferDockerDependencies(InferDependenciesRequest):
    infer_from = DockerInferenceFieldSet


@rule
async def infer_docker_dependencies(
    request: InferDockerDependencies, all_packageable_targets: AllPackageableTargets
) -> InferredDependencies:
    """Inspects the Dockerfile for references to known packageable targets."""
    dockerfile_info = await parse_dockerfile(
        DockerfileInfoRequest(request.field_set.address), **implicitly()
    )
    targets = await resolve_targets(**implicitly(Addresses([request.field_set.address])))
    build_args = await docker_build_args(
        DockerBuildArgsRequest(targets.expect_single()), **implicitly()
    )
    dockerfile_build_args = dockerfile_info.from_image_build_args.with_overrides(
        build_args
    ).nonempty()

    putative_image_addresses = set(
        await resolve_unparsed_address_inputs(
            UnparsedAddressInputs(
                dockerfile_build_args.values(),
                owning_address=dockerfile_info.address,
                description_of_origin=softwrap(
                    f"""
                    the FROM arguments from the file {dockerfile_info.source}
                    from the target {dockerfile_info.address}
                    """
                ),
                skip_invalid_addresses=True,
            ),
            **implicitly(),
        )
    )
    putative_copy_target_addresses = set(
        await resolve_unparsed_address_inputs(
            UnparsedAddressInputs(
                dockerfile_info.copy_build_args.nonempty().values(),
                owning_address=dockerfile_info.address,
                description_of_origin=softwrap(
                    f"""
                    the COPY arguments from the file {dockerfile_info.source}
                    from the target {dockerfile_info.address}
                    """
                ),
                skip_invalid_addresses=True,
            ),
            **implicitly(),
        )
    )
    maybe_output_paths = set(dockerfile_info.copy_source_paths) | set(
        dockerfile_info.copy_build_args.nonempty().values()
    )

    # NB: There's no easy way of knowing the output path's default file ending as there could
    # be none or it could be dynamic. Instead of forcing clients to tell us, we just use all the
    # possible ones from the Dockerfile. In rare cases we over-infer, but it is relatively harmless.
    # NB: The suffix gets an `or None` `pathlib` includes the ".", but `OutputPathField` doesn't
    # expect it (if you give it "", it'll leave a trailing ".").
    possible_file_endings = {PurePath(path).suffix[1:] or None for path in maybe_output_paths}
    output_paths_per_ending = await concurrently(
        packageable_output_paths(PackageableOutputPathsRequest(file_ending), **implicitly())
        for file_ending in sorted(possible_file_endings, key=lambda e: e or "")
    )
    positions = (await packageable_target_positions(**implicitly())).positions

    # Targets which are images we depend on.
    image_positions = {positions[a] for a in putative_image_addresses if a in positions}
    # Targets which look like they could generate a file we're trying to COPY.
    output_path_positions = {
        position
        for output_paths in output_paths_per_ending
        for path in maybe_output_paths
        for position in output_paths.positions_by_path.get(path, ())
    }
    # Targets with the same address as an ARG that will eventually be copied.
    copy_positions = {positions[a] for a in putative_copy_target_addresses if a in positions}

    inferred_addresses = []
    for position in sorted(image_positions | output_path_positions | copy_positions):
        address = all_packageable_targets[position].address
        if position in image_positions:
            inferred_addresses.append(address)
            continue
        if position in output_path_positions:
            inferred_addresses.append(address)
        if position in copy_positions:
            inferred_addresses.append(address)

    # add addresses from source paths if they are files directly
    addresses_from_source_paths = await resolve_targets(
        **implicitly(
            RawSpecs(
                description_of_origin="halp",
                unmatched_glob_behavior=GlobMatchErrorBehavior.ignore,
                file_literals=tuple(
                    FileLiteralSpec(e)
                    for e in [
                        *dockerfile_info.copy_source_paths,
                        *dockerfile_info.copy_build_args.nonempty().values(),
                    ]
                ),
            )
        )
    )

    inferred_addresses.extend(e.address for e in addresses_from_source_paths)

    return InferredDependencies(Addresses(inferred_addresses))


def rules():
    return [
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferDockerDependencies),
    ]
