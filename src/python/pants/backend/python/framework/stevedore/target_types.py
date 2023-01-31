# Copyright 2023 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import collections.abc
import os
from dataclasses import dataclass

from pants.backend.python.target_types import EntryPoint, PythonResolveField
from pants.engine.addresses import Address
from pants.engine.collection import Collection
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    AsyncFieldMixin,
    Dependencies,
    Field,
    InvalidFieldException,
    InvalidFieldTypeException,
    SecondaryOwnerMixin,
    StringField,
    StringSequenceField,
    Target,
    Targets,
)
from pants.source.filespec import Filespec
from pants.util.strutil import softwrap


@dataclass(frozen=True)
class StevedoreEntryPoint:
    name: str
    value: EntryPoint


class StevedoreEntryPoints(Collection[StevedoreEntryPoint]):
    pass


class StevedoreNamespaceField(StringField):
    alias = "namespace"
    help = softwrap(
        """
        Set the stevedore extension namespace.

        This looks like a python module 'my.stevedore.namespace', but a python module
        of that name does not need to exist. This is what a stevedore ExtensionManager
        uses to look up relevant entry_points from pkg_resources.
        """
    )
    required = True


class StevedoreEntryPointsField(AsyncFieldMixin, SecondaryOwnerMixin, Field):
    # based on pants.backend.python.target_types.PexEntryPointField
    # and on pants.backend.python.engine.target.DictStringToStringField
    alias = "entry_points"
    help = softwrap(
        """
        Map stevedore extension names to the entry_point that implements each name.

        Specify each entry_point to a module stevedore should use for the given extension name.
        You can specify a full module like 'path.to.module' and 'path.to.module:func', or use a
        shorthand to specify a file name, using the same syntax as the `sources` field:

          1) 'app.py', Pants will convert into the module `path.to.app`;
          2) 'app.py:func', Pants will convert into `path.to.app:func`.

        You must use the file name shorthand for file arguments to work with this target.
        """
    )
    required = True
    value: StevedoreEntryPoints

    @classmethod
    def compute_value(
        cls, raw_value: dict[str, str] | None, address: Address
    ) -> StevedoreEntryPoints:
        # TODO: maybe support raw entry point maps like ["name = path.to.module:func"]
        #       raw_value: Union[dict[str, str], list[str]]
        raw_entry_points = super().compute_value(raw_value, address)

        # DictStringToStringField validation
        invalid_type_exception = InvalidFieldTypeException(
            address, cls.alias, raw_value, expected_type="a dictionary of string -> string"
        )
        if not isinstance(raw_entry_points, collections.abc.Mapping):
            raise invalid_type_exception
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in raw_entry_points.items()):
            raise invalid_type_exception

        # convert to Collection[StevedoreEntryPoint]
        entry_points = []
        for name, value in raw_entry_points.items():
            try:
                entry_point = EntryPoint.parse(value, provenance=f"for {name} on {address}")
            except ValueError as e:
                raise InvalidFieldException(str(e))
            entry_points.append(StevedoreEntryPoint(name=name, value=entry_point))
        return StevedoreEntryPoints(entry_points)

    @property
    def filespec(self) -> Filespec:
        includes = []
        for entry_point in self.value:
            if not entry_point.value.module.endswith(".py"):
                continue
            full_glob = os.path.join(self.address.spec_path, entry_point.value.module)
            includes.append(full_glob)
        return {"includes": includes}


# See `target_types_rules.py` for the `ResolveStevedoreEntryPointsRequest -> ResolvedStevedoreEntryPoints` rule.
@dataclass(frozen=True)
class ResolvedStevedoreEntryPoints:
    val: StevedoreEntryPoints | None


@dataclass(frozen=True)
class ResolveStevedoreEntryPointsRequest:
    """Determine the `entry_points` for a StevedoreExtension after applying all syntactic sugar."""

    entry_points_field: StevedoreEntryPointsField


class StevedoreExtension(Target):
    alias = "stevedore_extension"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        StevedoreNamespaceField,
        StevedoreEntryPointsField,
        Dependencies,
        PythonResolveField,
    )
    help = "Entry points used to generate setuptools metadata for stevedore."


# This is a lot like a SpecialCasedDependencies field, but it doesn't list targets directly.
class StevedoreNamespacesField(StringSequenceField):
    alias = "stevedore_namespaces"
    help = softwrap(
        """
        List the stevedore namespaces required by this target.

        All stevedore_extension targets with these namespaces will be added as
        dependencies so that they are available on PYTHONPATH during tests.
        The stevedore namespace format (my.stevedore.extension) is similar
        to a python namespace.
        """
    )


class AllStevedoreExtensionTargets(Targets):
    pass
