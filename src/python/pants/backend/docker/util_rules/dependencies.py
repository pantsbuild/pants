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
    merged_from_build_args = {
        k: build_args.to_dict().get(k, v)
        for k, v in dockerfile_info.from_image_build_args.to_dict().items()
    }
    dockerfile_build_args = {k: v for k, v in merged_from_build_args.items() if v}

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
    maybe_output_paths = set(dockerfile_info.copy_source_paths)

    # NB: There's no easy way of knowing the output path's default file ending as there could
    # be none or it could be dynamic. Instead of forcing clients to tell us, we just use all the
    # possible ones from the Dockerfile. In rare cases we over-infer, but it is relatively harmless.
    # NB: The suffix gets an `or None` `pathlib` includes the ".", but `OutputPathField` doesn't
    # expect it (if you give it "", it'll leave a trailing ".").
    possible_file_endings = {PurePath(path).suffix[1:] or None for path in maybe_output_paths}
    inferred_addresses = []
    for target in all_packageable_targets:
        if target.address in putative_image_addresses:
            inferred_addresses.append(target.address)
            continue

        output_path_field = target.get(OutputPathField)
        possible_output_paths = {
            output_path_field.value_or_default(file_ending=file_ending)
            for file_ending in possible_file_endings
        }
        for output_path in possible_output_paths:
            if output_path in maybe_output_paths:
                inferred_addresses.append(target.address)
                break

    return InferredDependencies(Addresses(inferred_addresses))


def rules():
    return [
        *collect_rules(),
        UnionRule(InferDependenciesRequest, InferDockerDependencies),
    ]
