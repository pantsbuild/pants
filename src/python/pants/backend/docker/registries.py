# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from pants.option.parser import Parser
from pants.util.frozendict import FrozenDict

DEFAULT_REGISTRY = "@<default>"


class DockerRegistryError(ValueError):
    pass


class DockerRegistryOptionsNotFoundError(DockerRegistryError):
    def __init__(self, message):
        super().__init__(
            f"{message}\n\n"
            "Use the [docker].registries configuration option to define custom registries."
        )


@dataclass(frozen=True)
class DockerRegistryOptions:
    address: str
    alias: str = ""
    default: bool = False

    @classmethod
    def from_dict(cls, alias: str, d: dict[str, Any]) -> DockerRegistryOptions:
        return cls(
            alias=alias,
            address=d["address"],
            default=Parser.ensure_bool(d.get("default", alias == "default")),
        )

    def register(self, registries: dict[str, DockerRegistryOptions]) -> None:
        registries[self.address] = self
        if self.alias:
            registries[f"@{self.alias}"] = self
        if self.default:
            registries[DEFAULT_REGISTRY] = self


@dataclass(frozen=True)
class DockerRegistries:
    registries: FrozenDict[str, DockerRegistryOptions]

    def __post_init__(self):
        defaults = set()
        for alias, registry in self.registries.items():
            if registry.default:
                defaults.add(registry)
        if len(defaults) > 1:
            raise DockerRegistryError(
                "Multiple default Docker registries in the [docker].registries configuration: "
                + ", ".join(registry.alias for registry in defaults)
                + "."
            )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DockerRegistries:
        registries: dict[str, DockerRegistryOptions] = {}
        for alias, options in d.items():
            DockerRegistryOptions.from_dict(alias, options).register(registries)
        return cls(FrozenDict(registries))

    def __getitem__(self, alias_or_address: str | None) -> DockerRegistryOptions:
        return cast(DockerRegistryOptions, self.get(alias_or_address, implicit_options=False))

    def get(
        self, alias_or_address: str | None, implicit_options: bool = True
    ) -> DockerRegistryOptions | None:
        if not alias_or_address:
            return None

        if alias_or_address in self.registries:
            return self.registries[alias_or_address]
        elif alias_or_address == DEFAULT_REGISTRY:
            if not implicit_options:
                raise DockerRegistryOptionsNotFoundError(
                    "There is no default Docker registry configured."
                )
            else:
                return None
        elif alias_or_address.startswith("@"):
            raise DockerRegistryOptionsNotFoundError(
                f"There is no Docker registry configured with alias: {alias_or_address[1:]}."
            )
        elif implicit_options:
            return DockerRegistryOptions(address=alias_or_address)
        else:
            raise DockerRegistryOptionsNotFoundError(
                f"Unknown Docker registry: {alias_or_address}."
            )
