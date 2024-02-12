# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator

from pants.option.parser import Parser
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap

ALL_DEFAULT_REGISTRIES = "<all default registries>"


class DockerRegistryError(ValueError):
    pass


class DockerRegistryOptionsNotFoundError(DockerRegistryError):
    def __init__(self, message):
        super().__init__(
            f"{message}\n\n"
            "Use the [docker].registries configuration option to define custom registries."
        )


class DockerRegistryAddressCollisionError(DockerRegistryError):
    def __init__(self, first, second):
        message = softwrap(
            f"""
            Duplicated docker registry address for aliases: {first.alias}, {second.alias}.
            Each registry `address` in `[docker].registries` must be unique.
            """
        )

        super().__init__(message)


@dataclass(frozen=True)
class DockerRegistryOptions:
    address: str
    alias: str = ""
    default: bool = False
    skip_push: bool = False
    extra_image_tags: tuple[str, ...] = ()
    repository: str | None = None
    use_local_alias: bool = False

    @classmethod
    def from_dict(cls, alias: str, d: dict[str, Any]) -> DockerRegistryOptions:
        return cls(
            alias=alias,
            address=d["address"],
            default=Parser.ensure_bool(d.get("default", alias == "default")),
            skip_push=Parser.ensure_bool(d.get("skip_push", DockerRegistryOptions.skip_push)),
            extra_image_tags=tuple(
                d.get("extra_image_tags", DockerRegistryOptions.extra_image_tags)
            ),
            repository=Parser.to_value_type(d.get("repository"), str, None),
            use_local_alias=Parser.ensure_bool(d.get("use_local_alias", False)),
        )

    def register(self, registries: dict[str, DockerRegistryOptions]) -> None:
        if self.address in registries:
            collision = registries[self.address]
            raise DockerRegistryAddressCollisionError(collision, self)
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

    def get(self, *aliases_or_addresses: str) -> Iterator[DockerRegistryOptions]:
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
                # Assume an explicit address from the BUILD file.
                yield DockerRegistryOptions(address=alias_or_address)
