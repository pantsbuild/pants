# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.docker.registries import (
    DockerRegistries,
    DockerRegistryOptions,
    DockerRegistryOptionsNotFoundError,
)


def test_docker_registries() -> None:
    registries = DockerRegistries.from_dict(
        {
            "reg1": {"address": "myregistry1domain:port"},
            "reg2": {"address": "myregistry2domain:port"},
        }
    )

    assert registries.default == ()
    assert list(registries.get()) == []
    assert len(list(registries.get("@reg1"))) == 1
    assert len(list(registries.get("@reg2"))) == 1
    assert len(list(registries.get("@reg1", "@reg2"))) == 2
    assert next(registries.get("@reg1")).address == "myregistry1domain:port"
    assert next(registries.get("@reg2")).address == "myregistry2domain:port"
    assert next(registries.get("@reg2")).default is False
    assert [r.address for r in registries.get("@reg1", "@reg2")] == [
        "myregistry1domain:port",
        "myregistry2domain:port",
    ]

    with pytest.raises(DockerRegistryOptionsNotFoundError):
        list(registries.get("@reg3"))

    assert list(registries.get("myregistry3domain:port")) == [
        DockerRegistryOptions(address="myregistry3domain:port")
    ]


def test_default_registries() -> None:
    registries = DockerRegistries.from_dict(
        {
            "reg1": {"address": "myregistry1domain:port", "default": "false"},
            "reg2": {"address": "myregistry2domain:port", "default": "true"},
            "reg3": {"address": "myregistry3domain:port", "default": "true"},
        }
    )

    assert next(registries.get("@reg2")).default is True
    assert [r.address for r in registries.default] == [
        "myregistry2domain:port",
        "myregistry3domain:port",
    ]

    # Implicit registry options from address.
    assert next(registries.get("myunregistereddomain:port")) == DockerRegistryOptions(
        address="myunregistereddomain:port"
    )


def test_registry_image_ref() -> None:
    registries = DockerRegistries.from_dict(
        {
            "reg1": {"address": "myregistry1domain:port"},
            "reg2": {"address": False},
        }
    )

    assert (
        next(registries.get("@reg1")).get_image_ref("repo/name:tag")
        == "myregistry1domain:port/repo/name:tag"
    )
    assert next(registries.get("@reg2")).get_image_ref("repo/name:tag") == "repo/name:tag"
    assert next(registries.get("@reg2")).address is None

    with pytest.raises(ValueError):
        next(registries.get("@reg1")).get_image_ref("")


def test_invalid_registry_address() -> None:
    with pytest.raises(ValueError):
        DockerRegistries.from_dict({"reg1": {"address": True}})


def test_missing_registry_address() -> None:
    with pytest.raises(ValueError):
        DockerRegistries.from_dict({"reg1": {"default": True}})
