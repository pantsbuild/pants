# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Dict, Optional

from pants.engine.addresses import Address
from pants.engine.fs import AddPrefix, RemovePrefix, Snapshot
from pants.engine.rules import Get, rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    DictStringToStringField,
    InvalidFieldException,
    Sources,
    Target,
)
from pants.util.frozendict import FrozenDict

# -----------------------------------------------------------------------------------------------
# `files` target
# -----------------------------------------------------------------------------------------------


class FilesSources(Sources):
    required = True


class SourcesPrefixMapping(DictStringToStringField):
    """Change the prefix for the `sources` field to no longer be the path to the BUILD file (the
    default).

    To remove part of the original prefix, use `{"old_prefix": ""}`, which would change
    `old_prefix/f.ext` to `f.ext`. To add to the beginning of the
    original prefix, use `{"": "new_prefix"}`, which would change `f.ext` to `new_prefix/f.ext`.
    To both remove and add a prefix, use `{"old_prefix": "new_prefix"}`, which would change
    `old_prefix/f.ext` to `new_prefix/f.ext`.

    When removing a prefix, that prefix must actually be part of the original prefix, i.e. the path
    to the BUILD file.

    You should only use entry in the dictionary because this mapping will be applied to every file
    in the `sources` field.

    You can run `./pants filedeps` to verify that the mapping is working as you intended.
    """

    alias = "sources_prefix_mapping"

    @classmethod
    def compute_value(
        cls, raw_value: Optional[Dict[str, str]], *, address: Address
    ) -> Optional[FrozenDict[str, str]]:
        value = super().compute_value(raw_value, address=address)
        if value is None:
            return None
        if len(value) > 1:
            raise InvalidFieldException(
                f"The {repr(cls.alias)} field in target {address} should not have more than one "
                f"entry in its dictionary, but it had {len(value)} entries.\n\nWhy is this an "
                "issue? The path manipulation will be able to be applied to every file in the "
                "target's `sources` field, so they must all have a common prefix.\n\nIf you want "
                "more complex logic, such as conditional path manipulation, instead use more "
                "granular targets."
            )
        return value

    @property
    def remove_prefix(self) -> Optional[str]:
        """What prefix to remove from the hydrated sources, if any."""
        if not self.value:
            return None
        return tuple(self.value.keys())[0] or None

    @property
    def add_prefix(self) -> Optional[str]:
        """What prefix to add to the hydrated sources, if any.

        This should only be applied after first removing the prefix via the property
        `remove_prefix`.
        """
        if not self.value:
            return None
        return tuple(self.value.values())[0] or None


class Files(Target):
    """A collection of loose files which do not have their source roots stripped.

    The sources of a `files` target can be accessed via language-specific APIs, such as Python's
    `open()`. Unlike the similar `resources()` target type, Pants will not strip the source root of
    `files()`, meaning that `src/python/project/f1.txt` will not be stripped down to
    `project/f1.txt`.

    Unlike other target types, you may also change the prefix for the `sources` field to be different
    than the path to the BUILD file by setting `sources_prefix_mapping`.
    """

    alias = "files"
    core_fields = (*COMMON_TARGET_FIELDS, SourcesPrefixMapping, Dependencies, FilesSources)


@dataclass(frozen=True)
class ApplyPrefixMappingRequest:
    hydrated_sources: Snapshot
    prefix_mapping: SourcesPrefixMapping


@dataclass(frozen=True)
class PrefixMappedSnapshot:
    snapshot: Snapshot


@rule
async def apply_prefix_mapping(request: ApplyPrefixMappingRequest) -> PrefixMappedSnapshot:
    snapshot = request.hydrated_sources
    if request.prefix_mapping.remove_prefix:
        snapshot = await Get(
            Snapshot, RemovePrefix(snapshot.digest, request.prefix_mapping.remove_prefix)
        )
    if request.prefix_mapping.add_prefix:
        snapshot = await Get(
            Snapshot, AddPrefix(snapshot.digest, request.prefix_mapping.add_prefix)
        )
    return PrefixMappedSnapshot(snapshot)


# -----------------------------------------------------------------------------------------------
# `resources` target
# -----------------------------------------------------------------------------------------------


class ResourcesSources(Sources):
    required = True


class Resources(Target):
    """A collection of loose files.

    The sources of a `resources` target can be accessed via language-specific APIs, such as Python's
    `open()`. Resources are meant to be included in deployable units like JARs or Python wheels.
    Unlike the similar `files()` target type, Pants will strip the source root of `resources()`,
    meaning that `src/python/project/f1.txt` will be stripped down to `project/f1.txt`.
    """

    alias = "resources"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies, ResourcesSources)


# -----------------------------------------------------------------------------------------------
# `target` generic target
# -----------------------------------------------------------------------------------------------


class GenericTarget(Target):
    """A generic target with no specific target type.

    This can be used as a generic "bag of dependencies", i.e. you can group several different
    targets into one single target so that your other targets only need to depend on one thing.
    """

    alias = "target"
    core_fields = (*COMMON_TARGET_FIELDS, Dependencies)
