# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

from dataclasses import dataclass

from pants.build_graph.address import Address
from pants.engine.environment import EnvironmentName
from pants.engine.unions import union
from pants.util.frozendict import FrozenDict


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class GoModuleImportPathsMappingsHook:
    """An entry point for a specific implementation of mapping Go import paths to owning targets.

    All implementations will be merged together. The core Go dependency inference rules will request
    the `GoModuleImportPathsMappings` type using implementations of this union.
    """


@dataclass(frozen=True)
class GoImportPathsMappingAddressSet:
    addresses: tuple[Address, ...]
    infer_all: bool


@dataclass(frozen=True)
class GoModuleImportPathsMapping:
    """Maps import paths (as strings) to one or more addresses of targets providing those import
    path(s) for a single Go module."""

    mapping: FrozenDict[str, GoImportPathsMappingAddressSet]
    address_to_import_path: FrozenDict[Address, str]


@dataclass(frozen=True)
class GoModuleImportPathsMappings:
    """Import path mappings for all Go modules in the repository.

    This type is requested from plugins which provide implementations for the GoCodegenBuildRequest
    union and then merged.
    """

    modules: FrozenDict[Address, GoModuleImportPathsMapping]


class AllGoModuleImportPathsMappings(GoModuleImportPathsMappings):
    pass
