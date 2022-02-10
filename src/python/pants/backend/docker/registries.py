# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generator, Mapping

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
    address: str | None
    alias: str = ""
    default: bool = False

    @classmethod
    def from_dict(cls, alias: str, d: Mapping[str, Any]) -> DockerRegistryOptions:
        if "address" not in d:
            raise ValueError(f"Missing address option in Docker registry configuration {d!r}.")
        address = d["address"] or None
        if not isinstance(address, str) and address is not None:
            raise ValueError(
                f"Invalid Docker registry address, expected string but got {address!r}."
            )
        return cls(
            alias=alias,
            address=address,
            default=Parser.ensure_bool(d.get("default", alias == "default")),
        )

    def register(self, registries: dict[str, DockerRegistryOptions]) -> None:
        if self.address:
            registries[self.address] = self
        if self.alias:
            registries[f"@{self.alias}"] = self

    def get_image_ref(self, image_name: str) -> str:
        if not image_name:
            raise ValueError("Must provide image name.")
        if self.address:
            return "/".join([self.address, image_name])
        return image_name


@dataclass(frozen=True)
class DockerRegistries:
    default: tuple[DockerRegistryOptions, ...]
    registries: FrozenDict[str, DockerRegistryOptions]

    @classmethod
    def from_dict(cls, d: Mapping[str, Mapping[str, Any]]) -> DockerRegistries:
        registries: dict[str, DockerRegistryOptions] = {}
        for alias, options in d.items():
            DockerRegistryOptions.from_dict(alias, options).register(registries)
        return cls(
            default=tuple(
                sorted({r for r in registries.values() if r.default}, key=lambda r: r.address or "")
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
