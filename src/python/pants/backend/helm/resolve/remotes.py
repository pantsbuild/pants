# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABC
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


class InvalidHelmClassicRepositoryAddress(ValueError):
    def __init__(self, alias: str, address: str) -> None:
        super().__init__(
            f"The classic repository '{alias}' can not have an OCI address URL "
            f"(using protocol '{OCI_REGISTRY_PROTOCOL}'). The given address was instead: {address}"
        )


class HelmRemoteAliasNotFoundError(ValueError):
    def __init__(self, alias: str) -> None:
        super().__init__(f"There is no Helm remote configured with alias: {alias}")


@dataclass(frozen=True)
class HelmRemote(ABC):
    address: str
    alias: str = ""

    def register(self, remotes: dict[str, HelmRemote]) -> None:
        remotes[self.address] = self
        if self.alias:
            remotes[f"@{self.alias}"] = self


@dataclass(frozen=True)
class HelmRegistry(HelmRemote):
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


@dataclass(frozen=True)
class HelmClassicRepository(HelmRemote):
    @classmethod
    def from_dict(cls, alias: str, d: dict[str, Any]) -> HelmClassicRepository:
        return cls(alias=alias, address=cast(str, d["address"]).rstrip("/"))

    def __post_init__(self) -> None:
        if self.address.startswith(OCI_REGISTRY_PROTOCOL):
            raise InvalidHelmClassicRepositoryAddress(self.alias, self.address)


@dataclass(frozen=True)
class HelmRemotes:
    default: tuple[HelmRegistry, ...]
    all: FrozenDict[str, HelmRemote]

    @classmethod
    def from_dicts(cls, d_regs: dict[str, Any], d_repos: dict[str, Any]) -> HelmRemotes:
        remotes: dict[str, HelmRemote] = {}
        for alias, opts in d_regs.items():
            HelmRegistry.from_dict(alias, opts).register(remotes)
        for alias, opts in d_repos.items():
            HelmClassicRepository.from_dict(alias, opts).register(remotes)
        return cls(
            default=tuple(
                sorted(
                    {r for r in remotes.values() if isinstance(r, HelmRegistry) and r.default},
                    key=lambda r: r.address,
                )
            ),
            all=FrozenDict(remotes),
        )

    def get(self, *aliases_or_addresses: str) -> Iterator[HelmRemote]:
        for alias_or_address in aliases_or_addresses:
            if alias_or_address in self.all:
                yield self.all[alias_or_address]
            elif alias_or_address.startswith("@"):
                raise HelmRemoteAliasNotFoundError(alias_or_address)
            elif alias_or_address == ALL_DEFAULT_HELM_REGISTRIES:
                yield from self.default
            elif alias_or_address.startswith(OCI_REGISTRY_PROTOCOL):
                yield HelmRegistry(address=alias_or_address)
            else:
                yield HelmClassicRepository(address=alias_or_address)

    @memoized_method
    def classic_repositories(self) -> tuple[HelmClassicRepository, ...]:
        deduped_repos = {r for _, r in self.all.items() if isinstance(r, HelmClassicRepository)}
        return tuple(deduped_repos)

    @property
    def default_registry(self) -> HelmRegistry | None:
        remote = self.all.get("default")
        if remote:
            return cast(HelmRegistry, remote)
        if not remote and self.default:
            return self.default[0]
        return None
