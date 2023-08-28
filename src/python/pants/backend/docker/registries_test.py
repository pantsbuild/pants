# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import pytest

from pants.backend.docker.registries import (
    DockerRegistries,
    DockerRegistryAddressCollisionError,
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

    # Test defaults.
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


def test_skip_push() -> None:
    registries = DockerRegistries.from_dict(
        {
            "reg1": {"address": "registry1"},
            "reg2": {"address": "registry2", "skip_push": True},
            "reg3": {"address": "registry3", "skip_push": "false"},
        }
    )

    reg1, reg2, reg3 = registries.get("@reg1", "@reg2", "@reg3")
    assert reg1.skip_push is False
    assert reg2.skip_push is True
    assert reg3.skip_push is False


def test_extra_image_tags() -> None:
    registries = DockerRegistries.from_dict(
        {
            "reg1": {"address": "registry1"},
            "reg2": {
                "address": "registry2",
                "extra_image_tags": ["latest", "v{build_args.VERSION}"],
            },
        }
    )

    reg1, reg2 = registries.get("@reg1", "@reg2")
    assert reg1.extra_image_tags == ()
    assert reg2.extra_image_tags == ("latest", "v{build_args.VERSION}")


def test_repository() -> None:
    registries = DockerRegistries.from_dict(
        {"reg1": {"address": "registry1", "repository": "{name}/foo"}}
    )
    (reg1,) = registries.get("@reg1")
    assert reg1.repository == "{name}/foo"


def test_registries_must_be_unique() -> None:
    with pytest.raises(DockerRegistryAddressCollisionError) as e:
        DockerRegistries.from_dict(
            {
                "reg1": {"address": "mydomain:port"},
                "reg2": {"address": "mydomain:port"},
            }
        )

    assert e.match("Duplicated docker registry address for aliases: reg1, reg2.")
