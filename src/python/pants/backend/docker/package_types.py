# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass

from pants.core.goals.package import BuiltPackageArtifact
from pants.util.strutil import bullet_list, pluralize


@dataclass(frozen=True)
class BuiltDockerImage(BuiltPackageArtifact):
    # We don't really want a default for this field, but the superclass has a field with
    # a default, so all subsequent fields must have one too. The `create()` method below
    # will ensure that this field is properly populated in practice.
    image_id: str = ""
    tags: tuple[str, ...] = ()

    @classmethod
    def create(
        cls, image_id: str, tags: tuple[str, ...], metadata_filename: str
    ) -> BuiltDockerImage:
        tags_string = tags[0] if len(tags) == 1 else f"\n{bullet_list(tags)}"
        return cls(
            image_id=image_id,
            tags=tags,
            relpath=metadata_filename,
            extra_log_lines=(
                f"Built docker {pluralize(len(tags), 'image', False)}: {tags_string}",
                f"Docker image ID: {image_id}",
            ),
        )
