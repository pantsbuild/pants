# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools

import pytest

from pants.backend.helm.utils.docker import ImageRef

_REGISTRIES = [None, "myregistry", "myregistry.example.com"]
_REPOSITORIES = ["simple", "folder/simple"]
_TAGS = [None, "latest", "1.2.3.4"]


def _build_parameters() -> list[tuple[str, str | None, str, str | None]]:
    result = []
    for (registry, repo, tag) in itertools.product(_REGISTRIES, _REPOSITORIES, _TAGS):
        if "/" in repo and not registry:
            continue

        image_ref = repo
        if registry:
            image_ref = f"{registry}/{image_ref}"
        if tag:
            image_ref = f"{image_ref}:{tag}"

        result.append((image_ref, registry, repo, tag))
    return result


@pytest.mark.parametrize("image_ref, registry, repository, tag", _build_parameters())
def test_parses_valid_docker_image_refs(
    image_ref: str, registry: str | None, repository: str, tag: str | None
) -> None:
    parsed = ImageRef.parse(image_ref)

    assert parsed.registry == registry
    assert parsed.repository == repository
    assert parsed.tag == tag
