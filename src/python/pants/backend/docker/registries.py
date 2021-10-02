# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generator

from pants.option.parser import Parser
from pants.util.frozendict import FrozenDict

ALL_DEFAULT_REGISTRIES = "<all default registries>"


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


@dataclass(frozen=True)
class DockerRegistries:
    default: tuple[DockerRegistryOptions, ...]
    registries: FrozenDict[str, DockerRegistryOptions]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DockerRegistries:
        registries: dict[str, DockerRegistryOptions] = {}
        for alias, options in d.items():
            DockerRegistryOptions.from_dict(alias, options).register(registries)
        return cls(
            default=tuple(
                sorted({r for r in registries.values() if r.default}, key=lambda r: r.address)
            ),
            registries=FrozenDict(registries),
        )

    def get(self, *aliases_or_addresses: str) -> Generator[DockerRegistryOptions, None, None]:
        for alias_or_address in aliases_or_addresses:
            if alias_or_address in self.registries:
                # Get configured registry by "@alias" or "address".
                yield self.registries[alias_or_address]
            elif alias_or_address.startswith("@"):
                raise DockerRegistryOptionsNotFoundError(
                    f"There is no Docker registry configured with alias: {alias_or_address[1:]}."
                )
            elif alias_or_address == ALL_DEFAULT_REGISTRIES:
                yield from self.default
            else:
                # Assume a explicit address from the BUILD file.
                yield DockerRegistryOptions(address=alias_or_address)
