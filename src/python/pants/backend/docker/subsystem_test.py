# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.docker.subsystem import DEFAULT_REGISTRY, DockerRegistries, DockerRegistryOptions


def test_docker_registries() -> None:
    registries = DockerRegistries.from_dict(
        {
            "reg1": {"address": "myregistry1domain:port"},
            "reg2": {"address": "myregistry2domain:port"},
        }
    )

    assert registries["reg1"].address == "myregistry1domain:port"
    assert registries["reg2"].address == "myregistry2domain:port"
    assert registries["reg2"].default is False
    assert registries.get("reg3") == DockerRegistryOptions(address="reg3")

    assert registries.get(None) is None
    assert registries.get(DEFAULT_REGISTRY) is None
    with pytest.raises(ValueError, match=r"There is no default Docker registry configured\."):
        registries[DEFAULT_REGISTRY]

    # Test default.
    registries = DockerRegistries.from_dict(
        {
            "reg1": {"address": "myregistry1domain:port"},
            "reg2": {"address": "myregistry2domain:port", "default": "true"},
        }
    )

    assert registries["reg2"].default is True
    assert registries.get(DEFAULT_REGISTRY) == registries["reg2"]
    assert registries.get(None) is None
    assert registries.get("") is None

    # Implicit registry options from address.
    assert registries.get("myunregistereddomain:port") == DockerRegistryOptions(
        address="myunregistereddomain:port"
    )

    # There may be at most one default.
    with pytest.raises(
        ValueError,
        match=(
            r"Multiple default Docker registries in the \[docker\]\.registries "
            r"configuration: reg1, reg2\."
        ),
    ):
        registries = DockerRegistries.from_dict(
            {
                "reg1": {"address": "myregistry1domain:port", "default": "true"},
                "reg2": {"address": "myregistry2domain:port", "default": "true"},
            }
        )
