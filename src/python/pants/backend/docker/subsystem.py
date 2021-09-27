# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from textwrap import dedent
from typing import Any, cast

from pants.option.parser import Parser
from pants.option.subsystem import Subsystem
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized_method


@dataclass(frozen=True)
class DockerRegistryOptions:
    address: str
    default: bool = False

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DockerRegistryOptions:
        return cls(
            address=d["address"],
            default=Parser.ensure_bool(d.get("default", False)),
        )


@dataclass(frozen=True)
class DockerRegistries:
    registries: FrozenDict[str, DockerRegistryOptions]

    def __post_init__(self):
        defaults = []
        for alias, registry in self.registries.items():
            if registry.default:
                defaults.append(alias)
        if len(defaults) > 1:
            raise ValueError(
                "Multiple default Docker registries in the [docker].registries configuration: "
                + ", ".join(defaults)
                + "."
            )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DockerRegistries:
        return cls(
            FrozenDict(
                {alias: DockerRegistryOptions.from_dict(options) for alias, options in d.items()}
            )
        )

    def __getitem__(self, alias_or_address: str | None) -> DockerRegistryOptions:
        return cast(DockerRegistryOptions, self.get(alias_or_address, implicit_options=False))

    def get(
        self, alias_or_address: str | None, implicit_options: bool = True
    ) -> DockerRegistryOptions | None:
        if alias_or_address == "":
            return None

        if alias_or_address is not None and alias_or_address in self.registries:
            return self.registries.get(alias_or_address)

        # The registries are expected to be very few, so this for loop is not that expensive.
        default: DockerRegistryOptions | None = None
        for registry in self.registries.values():
            if registry.address == alias_or_address:
                return registry
            if registry.default:
                default = registry

        if alias_or_address:
            if implicit_options:
                return DockerRegistryOptions(address=alias_or_address)

            raise ValueError(f"Unknown Docker registry: {alias_or_address}.")

        if default or implicit_options:
            return default

        raise ValueError("There is no default Docker registry configured.")


class DockerOptions(Subsystem):
    options_scope = "docker"
    help = "Options for interacting with Docker."

    @classmethod
    def register_options(cls, register):
        registries_help = (
            dedent(
                """\
            Configure Docker registries. The schema for a registry entry is as follows:

                {
                    "registry-alias": {
                        "address": "registry-domain:port",
                        "default": bool,
                    },
                    ...
                }

            """
            )
            + (
                "Only one registry may be declared as the default registry. If a registry value "
                "is not provided in a `docker_image` target, the address of the default registry "
                "will be used, if any.\n"
                "The `docker_image.registry` may be provided with either the registry address or "
                "the registry alias, or `None` if the image should not be associated with a custom "
                "registry."
            )
        )
        super().register_options(register)
        register("--registries", type=dict, fromfile=True, help=registries_help)

    @memoized_method
    def registries(self) -> DockerRegistries:
        return DockerRegistries.from_dict(self.options.registries)
