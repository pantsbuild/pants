# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePath

from pants.backend.docker.subsystems.dockerfile_parser import DockerfileInfo, DockerfileInfoRequest
from pants.backend.docker.target_types import DockerImageDependenciesField
from pants.backend.docker.util_rules.docker_build_args import (
    DockerBuildArgs,
    DockerBuildArgsRequest,
)
from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.base.specs import FileLiteralSpec, RawSpecs
from pants.core.goals.package import AllPackageableTargets, OutputPathField
from pants.engine.addresses import Addresses, UnparsedAddressInputs
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import FieldSet, InferDependenciesRequest, InferredDependencies, Targets
from pants.engine.unions import UnionRule
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class DockerInferenceFieldSet(FieldSet):
    required_fields = (DockerImageDependenciesField,)

    dependencies: DockerImageDependenciesField


class InferDockerDependencies(InferDependenciesRequest):
    infer_from = DockerInferenceFieldSet


@rule
async def infer_docker_dependencies(
    request: InferDockerDependencies, all_packageable_targets: AllPackageableTargets
) -> InferredDependencies:
    """Inspects the Dockerfile for references to known packageable targets."""
    dockerfile_info = await Get(DockerfileInfo, DockerfileInfoRequest(request.field_set.address))
    targets = await Get(Targets, Addresses([request.field_set.address]))
    build_args = await Get(DockerBuildArgs, DockerBuildArgsRequest(targets.expect_single()))
    dockerfile_build_args = dockerfile_info.from_image_build_args.with_overrides(
        build_args, only_with_value=True
    )

    putative_image_addresses = set(
        await Get(
            Addresses,
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
        )
    )
    putative_copy_target_addresses = set(
        await Get(
            Addresses,
            UnparsedAddressInputs(
                dockerfile_info.copy_build_args.to_dict().values(),
                owning_address=dockerfile_info.address,
                description_of_origin=softwrap(
                    f"""
                the COPY arguments from the file {dockerfile_info.source}
                from the target {dockerfile_info.address}
                """
                ),
                skip_invalid_addresses=True,
            ),
        )
    )
    maybe_output_paths = set(dockerfile_info.copy_source_paths) | set(
        dockerfile_info.copy_build_args.to_dict().values()
    )

    # NB: There's no easy way of knowing the output path's default file ending as there could
    # be none or it could be dynamic. Instead of forcing clients to tell us, we just use all the
    # possible ones from the Dockerfile. In rare cases we over-infer, but it is relatively harmless.
    # NB: The suffix gets an `or None` `pathlib` includes the ".", but `OutputPathField` doesn't
    # expect it (if you give it "", it'll leave a trailing ".").
    possible_file_endings = {PurePath(path).suffix[1:] or None for path in maybe_output_paths}
    inferred_addresses = []
    for target in all_packageable_targets:
        # If the target is an image we depend on, add it
        if target.address in putative_image_addresses:
            inferred_addresses.append(target.address)
            continue

        # If the target looks like it could generate the file we're trying to COPY
        output_path_field = target.get(OutputPathField)
        possible_output_paths = {
            output_path_field.value_or_default(file_ending=file_ending)
            for file_ending in possible_file_endings
        }
        for output_path in possible_output_paths:
            if output_path in maybe_output_paths:
                inferred_addresses.append(target.address)
                break

        # If the target has the same address as an ARG that will eventually be copied
        if target.address in putative_copy_target_addresses:
            inferred_addresses.append(target.address)

    # add addresses from source paths if they are files directly
    addresses_from_source_paths = await Get(
        Targets,
        RawSpecs(
            description_of_origin="halp",
            unmatched_glob_behavior=GlobMatchErrorBehavior.ignore,
            file_literals=tuple(
                FileLiteralSpec(e)
                for e in [
                    *dockerfile_info.copy_source_paths,
                    *dockerfile_info.copy_build_args.to_dict().values(),
                ]
            ),
        ),
    )

    inferred_addresses.extend(e.address for e in addresses_from_source_paths)

    return InferredDependencies(Addresses(inferred_addresses))


def rules():
    return [
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferDockerDependencies),
    ]
