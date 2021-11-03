# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from pants.backend.docker.target_types import DockerImageSourceField
from pants.engine.addresses import Address


def test_docker_image_source_field_does_not_leak_target_address_to_globs() -> None:
    source = DockerImageSourceField(":build-spec", Address("test"))
    assert source.value == ":build-spec"
    assert source.globs == ()
