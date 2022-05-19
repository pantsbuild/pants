# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable

from pants.util.frozendict import FrozenDict


class Spec(ABC):
    """A specification for what Pants should operate on."""

    @abstractmethod
    def __str__(self) -> str:
        """The normalized string representation of this spec."""


@dataclass(frozen=True)
class AddressLiteralSpec(Spec):
    """A single target address.

    This may be one of:

    * A traditional address, like `dir:lib`.
    * A generated target address like `dir:lib#generated` or `dir#generated`.
    * A file address using disambiguation syntax like dir/f.ext:lib`.
    """

    path_component: str
    target_component: str | None = None
    generated_component: str | None = None
    parameters: FrozenDict[str, str] = FrozenDict()

    def __str__(self) -> str:
        tgt = f":{self.target_component}" if self.target_component else ""
        generated = f"#{self.generated_component}" if self.generated_component else ""
        return f"{self.path_component}{tgt}{generated}"

    @property
    def is_directory_shorthand(self) -> bool:
        """Is in the format `path/to/dir`, which is shorthand for `path/to/dir:dir`."""
        return (
            self.target_component is None
            and self.generated_component is None
            and not self.parameters
        )


@dataclass(frozen=True)
class FileLiteralSpec(Spec):
    """A literal file name, e.g. `foo.py`.

    Matches:

    * Target-aware: all targets who include the file in their `source`/`sources` field.
    * Target-less: the file.
    """

    file: str

    def __str__(self) -> str:
        return self.file


@dataclass(frozen=True)
class FileGlobSpec(Spec):
    """A spec with a glob or globs, e.g. `*.py` and `**/*.java`.

    Matches:

    * Target-aware: all targets who include the file in their `source`/`sources` field.
    * Target-less: the file.
    """

    glob: str

    def __str__(self) -> str:
        return self.glob


@dataclass(frozen=True)
class DirLiteralSpec(Spec):
    """A literal dir path, e.g. `some/dir`.

    Matches:

    * Target-aware: (for now) the "default" target, i.e. whose `name=` matches the directory.
    * Target-less: all files in the directory.

    The empty string represents the build root.
    """

    directory: str

    def __str__(self) -> str:
        return self.directory


@dataclass(frozen=True)
class DirGlobSpec(Spec):
    """E.g. `some/dir:`.

    Matches:

    * Target-aware: all targets "resident" in a directory, i.e. defined there or generated into
      the dir.
    * Target-less: all files in the directory.

    The empty string represents the build root.
    """

    directory: str
    error_if_no_matches: bool = True

    def __str__(self) -> str:
        return f"{self.directory}:"


@dataclass(frozen=True)
class RecursiveGlobSpec(Spec):
    """E.g. `some/dir::`.

    Matches:

    * Target-aware: all targets "resident" in the directory and below, meaning they are defined
      there or generated there.
    * Target-less: all files in the directory and below.

    The empty string represents the build root.
    """

    directory: str
    error_if_no_matches: bool = True

    def __str__(self) -> str:
        return f"{self.directory}::"


@dataclass(frozen=True)
class AncestorGlobSpec(Spec):
    """E.g. `some/dir^`.

    Matches:

    * Target-aware: all targets "resident" in the directory and above, meaning they are defined
      there or generated there.
    * Target-less: all files in the directory and above.

    The empty string represents the build root.
    """

    directory: str

    def __str__(self) -> str:
        return f"{self.directory}^"


@dataclass(frozen=True)
class Specs:
    address_literals: tuple[AddressLiteralSpec, ...]
    file_literals: tuple[FileLiteralSpec, ...]
    file_globs: tuple[FileGlobSpec, ...]
    dir_literals: tuple[DirLiteralSpec, ...]
    dir_globs: tuple[DirGlobSpec, ...]
    recursive_globs: tuple[RecursiveGlobSpec, ...]
    ancestor_globs: tuple[AncestorGlobSpec, ...]

    filter_by_global_options: bool = False
    from_change_detection: bool = False

    @classmethod
    def create(
        cls,
        specs: Iterable[Spec],
        *,
        filter_by_global_options: bool = False,
        from_change_detection: bool = False,
    ) -> Specs:
        address_literals = []
        file_literals = []
        file_globs = []
        dir_literals = []
        dir_globs = []
        recursive_globs = []
        ancestor_globs = []
        for spec in specs:
            if isinstance(spec, AddressLiteralSpec):
                address_literals.append(spec)
            elif isinstance(spec, FileLiteralSpec):
                file_literals.append(spec)
            elif isinstance(spec, FileGlobSpec):
                file_globs.append(spec)
            elif isinstance(spec, DirLiteralSpec):
                dir_literals.append(spec)
            elif isinstance(spec, DirGlobSpec):
                dir_globs.append(spec)
            elif isinstance(spec, RecursiveGlobSpec):
                recursive_globs.append(spec)
            elif isinstance(spec, AncestorGlobSpec):
                ancestor_globs.append(spec)
            else:
                raise AssertionError(f"Unexpected type of Spec: {repr(spec)}")
        return Specs(
            tuple(address_literals),
            tuple(file_literals),
            tuple(file_globs),
            tuple(dir_literals),
            tuple(dir_globs),
            tuple(recursive_globs),
            tuple(ancestor_globs),
            filter_by_global_options=filter_by_global_options,
            from_change_detection=from_change_detection,
        )

    @property
    def provided(self) -> bool:
        """Were any specs given?"""
        return (
            self.address_literals or self.file_literals or self.file_globs or self.dir_literals or self.dir_globs or self.recursive_globs or self.ancestor_globs
        )


@dataclass(frozen=True)
class SpecsWithoutFileOwners:
    address_literals: tuple[AddressLiteralSpec, ...]
    dir_literals: tuple[DirLiteralSpec, ...]
    dir_globs: tuple[DirGlobSpec, ...]
    recursive_globs: tuple[RecursiveGlobSpec, ...]
    ancestor_globs: tuple[AncestorGlobSpec, ...]


@dataclass(frozen=True)
class SpecsWithOnlyFileOwners:
    file_literals: tuple[FileLiteralSpec, ...]
    file_globs: tuple[FileGlobSpec, ...]
