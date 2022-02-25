# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generator, cast

from pants.option.parser import Parser
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized_method

ALL_DEFAULT_HELM_REGISTRIES = "<ALL DEFAULT HELM REGISTRIES>"

OCI_REGISTRY_PROTOCOL = "oci://"


class HelmRegistryNotFoundError(ValueError):
    pass


class InvalidDefaultHelmRegistryError(ValueError):
    def __init__(self, alias: str, address: str) -> None:
        super().__init__(
            f"The registry '{alias}' at address '{address}' has an invalid `default = true` setting. "
            "Only OCI registries can be marked as `default`."
        )


@dataclass(frozen=True)
class HelmRegistry:
    address: str
    alias: str = ""
    default: bool = False

    @classmethod
    def from_dict(cls, alias: str, d: dict[str, Any]) -> HelmRegistry:
        address_url = cast(str, d["address"])
        return cls(
            alias=alias,
            address=address_url,
            default=Parser.ensure_bool(d.get("default", alias == "default")),
        )

    def __post_init__(self) -> None:
        if not self.is_oci and self.default:
            raise InvalidDefaultHelmRegistryError(self.alias, self.address)

    def register(self, registries: dict[str, HelmRegistry]) -> None:
        registries[self.address] = self
        if self.alias:
            registries[f"@{self.alias}"] = self

    @property
    def is_oci(self) -> bool:
        return self.address.startswith(OCI_REGISTRY_PROTOCOL)


@dataclass(frozen=True)
class HelmRegistries:
    default: tuple[HelmRegistry, ...]
    all: FrozenDict[str, HelmRegistry]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HelmRegistries:
        registries: dict[str, HelmRegistry] = {}
        for alias, options in d.items():
            HelmRegistry.from_dict(alias, options).register(registries)
        return cls(
            default=tuple(
                sorted({r for r in registries.values() if r.default}, key=lambda r: r.address)
            ),
            all=FrozenDict(registries),
        )

    def get(self, *aliases_or_addresses: str) -> Generator[HelmRegistry, None, None]:
        for alias_or_address in aliases_or_addresses:
            if alias_or_address in self.all:
                # Get configured registry by "@alias" or "address"
                yield self.all[alias_or_address]
            elif alias_or_address.startswith("@"):
                raise HelmRegistryNotFoundError(
                    f"There is no Helm registry configured with alias: {alias_or_address}"
                )
            elif alias_or_address == ALL_DEFAULT_HELM_REGISTRIES:
                yield from self.default
            else:
                yield HelmRegistry(address=alias_or_address)

    def get_address_of(self, addr: str) -> str | None:
        if addr not in self.all:
            return None
        return self.all[addr].address

    def get_alias_of(self, address: str) -> str | None:
        registry = self.all.get(address)
        if registry and registry.alias:
            return registry.alias
        else:
            return None

    @memoized_method
    def all_classic(self) -> tuple[HelmRegistry, ...]:
        return tuple({registry for _, registry in self.all.items() if not registry.is_oci})
