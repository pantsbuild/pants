# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os.path
from collections import defaultdict
from collections.abc import Sequence
from functools import partial
from itertools import chain
from typing import Any, DefaultDict, Iterator

from pants.backend.docker.target_types import (
    DockerImageTarget,
    DockerMirrorImagesSourcesField,
    DockerMirrorImagesSpecFileTarget,
    DockerMirrorImagesTarget,
)
from pants.backend.docker.utils import DockerImageRef, DockerImageRefParser
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.engine.addresses import Address
from pants.engine.fs import Digest, DigestContents
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import GeneratedTargets, GenerateTargetsRequest, OverridesField, Target
from pants.engine.unions import UnionMembership, UnionRule
from pants.util.dirutil import fast_relpath


class GenerateTargetsFromDockerMirrorImages(GenerateTargetsRequest):
    generate_from = DockerMirrorImagesTarget


def get_overrides(name: str, overrides: OverridesField) -> dict | None:
    if not overrides.value:
        return None

    for names, override_values in overrides.value.items():
        if name in names:
            return override_values

    return None


def apply_overrides(
    image_ref: DockerImageRef, overrides: OverridesField, values: dict[str, Any]
) -> dict[str, Any]:
    for name in [image_ref.name, image_ref.image]:
        if not name:
            continue
        override_values = get_overrides(name, overrides)
        if not override_values:
            continue
        for key, value in override_values.items():
            if key not in values:
                values[key] = value
            elif isinstance(value, Sequence) and isinstance(values[key], list):
                values[key].extend(value)
            elif not isinstance(value, type(values[key])):
                raise ValueError(
                    f"Attempt to override {name}.{key} with {value!r}, which is of another type "
                    f"than {type(values[key])}"
                )
            else:
                values[key] = value
    return values


class NameGenerator:
    def __init__(self, address: Address):
        self.address = address
        self.generated_names: DefaultDict[str, int] = defaultdict(int)

    def generate_name(self, name: str) -> Address:
        count = self.generated_names[name]
        self.generated_names[name] = count + 1
        if count > 0:
            name = f"{name}_{count}"
        return self.address.create_generated(name)


def generate_targets(
    filename: str,
    lines: Iterator[str],
    request: GenerateTargetsFromDockerMirrorImages,
    union_membership: UnionMembership,
) -> Iterator[Target]:
    address = request.generator.address
    overrides = request.generator[OverridesField]
    parser = DockerImageRefParser()
    relativized_fp = fast_relpath(filename, address.spec_path)
    name_generator = NameGenerator(address)
    spec_file_address = Address(
        address.spec_path,
        target_name=address.target_name,
        relative_file_path=relativized_fp,
    )

    yield DockerMirrorImagesSpecFileTarget(
        dict(source=relativized_fp),
        spec_file_address,
        union_membership,
        residence_dir=os.path.dirname(filename),
    )

    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        try:
            image_ref = parser.parse(line)
        except ValueError as e:
            raise ValueError(f"Failed to parse image ref in {filename}: {e}") from e

        docker_image_field_values = apply_overrides(
            image_ref,
            overrides,
            {
                "dependencies": [spec_file_address.spec],
                "instructions": [f"FROM {image_ref}"],
                "repository": image_ref.image,
                "tags": ["docker-mirror"],
            },
        )

        # Only set `image_tags` if it where not provided with the `overrides`.
        docker_image_field_values.setdefault("image_tags", [image_ref.image_tag])

        yield DockerImageTarget(
            docker_image_field_values,
            name_generator.generate_name(image_ref.target_name),
            union_membership,
        )


@rule
async def generate_targets_from_docker_mirror_images(
    request: GenerateTargetsFromDockerMirrorImages,
    union_membership: UnionMembership,
) -> GeneratedTargets:
    sources = await Get(
        SourceFiles,
        SourceFilesRequest([request.generator[DockerMirrorImagesSourcesField]]),
    )
    contents = await Get(DigestContents, Digest, sources.snapshot.digest)

    gen = partial(generate_targets, request=request, union_membership=union_membership)
    targets = chain(*[gen(c.path, c.content.decode().split("\n")) for c in contents])
    return GeneratedTargets(request.generator, targets)


def rules():
    return (
        *collect_rules(),
        UnionRule(GenerateTargetsRequest, GenerateTargetsFromDockerMirrorImages),
    )
