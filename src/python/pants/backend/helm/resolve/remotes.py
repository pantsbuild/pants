# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, cast

from pants.option.parser import Parser
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized_method

ALL_DEFAULT_HELM_REGISTRIES = "<ALL DEFAULT HELM REGISTRIES>"

OCI_REGISTRY_PROTOCOL = "oci://"


class InvalidHelmRegistryAddress(ValueError):
    def __init__(self, alias: str, address: str) -> None:
        super().__init__(
            f"The registry '{alias}' needs to have a valid OCI address URL "
            f"(using protocol '{OCI_REGISTRY_PROTOCOL}'). The given address was instead: {address}"
        )


class HelmRemoteAliasNotFoundError(ValueError):
    def __init__(self, alias: str) -> None:
        super().__init__(f"There is no Helm remote configured with alias: {alias}")


@dataclass(frozen=True)
class HelmRegistry:
    address: str
    alias: str = ""
    default: bool = False

    @classmethod
    def from_dict(cls, alias: str, d: dict[str, Any]) -> HelmRegistry:
        return cls(
            alias=alias,
            address=cast(str, d["address"]).rstrip("/"),
            default=Parser.ensure_bool(d.get("default", alias == "default")),
        )

    def __post_init__(self) -> None:
        if not self.address.startswith(OCI_REGISTRY_PROTOCOL):
            raise InvalidHelmRegistryAddress(self.alias, self.address)

    def register(self, remotes: dict[str, HelmRegistry]) -> None:
        remotes[self.address] = self
        if self.alias:
            remotes[f"@{self.alias}"] = self

    def repository_ref(self, repository: str | None) -> str:
        return f"{self.address}/{repository or ''}".rstrip("/")

    def package_ref(self, artifact_name: str, *, repository: str | None) -> str:
        repo_ref = self.repository_ref(repository)
        return f"{repo_ref}/{artifact_name}"


@dataclass(frozen=True)
class HelmRemotes:
    default: tuple[HelmRegistry, ...]
    all: FrozenDict[str, HelmRegistry]

    @classmethod
    def from_dict(cls, d_regs: dict[str, Any]) -> HelmRemotes:
        remotes: dict[str, HelmRegistry] = {}
        for alias, opts in d_regs.items():
            HelmRegistry.from_dict(alias, opts).register(remotes)
        return cls(
            default=tuple(
                sorted(
                    {r for r in remotes.values() if isinstance(r, HelmRegistry) and r.default},
                    key=lambda r: r.address,
                )
            ),
            all=FrozenDict(remotes),
        )

    def get(self, *aliases_or_addresses: str) -> Iterator[HelmRegistry]:
        for alias_or_address in aliases_or_addresses:
            if alias_or_address in self.all:
                yield self.all[alias_or_address]
            elif alias_or_address.startswith("@"):
                raise HelmRemoteAliasNotFoundError(alias_or_address)
            elif alias_or_address == ALL_DEFAULT_HELM_REGISTRIES:
                yield from self.default
            elif alias_or_address.startswith(OCI_REGISTRY_PROTOCOL):
                yield HelmRegistry(address=alias_or_address)

    @memoized_method
    def registries(self) -> tuple[HelmRegistry, ...]:
        return tuple(set(self.all.values()))

    @property
    def default_registry(self) -> HelmRegistry | None:
        remote = self.all.get("default")
        if not remote and self.default:
            remote = self.default[0]
        return remote
