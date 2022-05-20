# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Iterator, cast

from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.fs import GlobExpansionConjunction, PathGlobs
from pants.util.dirutil import fast_relpath_optional, recursive_dirname
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

    def to_glob(self) -> str:
        return self.file


@dataclass(frozen=True)
class FileGlobSpec(Spec):
    """A spec with a glob or globs, e.g. `*.py` and `**/*.java`.

    Matches:

    * Target-aware: all targets who include the file glob in their `source`/`sources` field.
    * Target-less: the files matching the glob.
    """

    glob: str

    def __str__(self) -> str:
        return self.glob

    def to_glob(self) -> str:
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

    def to_address_literal(self) -> AddressLiteralSpec:
        """For now, `dir` can also be shorthand for `dir:dir`."""
        return AddressLiteralSpec(path_component=self.directory)


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
    error_if_no_target_matches: bool = True

    def __str__(self) -> str:
        return f"{self.directory}:"

    def matches_target(self, tgt_residence_dir: str) -> bool:
        return tgt_residence_dir == self.directory


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
    error_if_no_target_matches: bool = True

    def __str__(self) -> str:
        return f"{self.directory}::"

    def matches_target(self, tgt_residence_dir: str) -> bool:
        return fast_relpath_optional(tgt_residence_dir, self.directory) is not None


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
    error_if_no_target_matches: bool = False

    def __str__(self) -> str:
        return f"{self.directory}^"

    def matches_target(self, tgt_residence_dir: str) -> bool:
        return fast_relpath_optional(self.directory, tgt_residence_dir) is not None


@dataclass(frozen=True)
class Specs:
    address_literals: tuple[AddressLiteralSpec, ...] = ()
    file_literals: tuple[FileLiteralSpec, ...] = ()
    file_globs: tuple[FileGlobSpec, ...] = ()
    dir_literals: tuple[DirLiteralSpec, ...] = ()
    dir_globs: tuple[DirGlobSpec, ...] = ()
    recursive_globs: tuple[RecursiveGlobSpec, ...] = ()
    ancestor_globs: tuple[AncestorGlobSpec, ...] = ()

    filter_by_global_options: bool = False
    from_change_detection: bool = False

    @classmethod
    def create(
        cls,
        specs: Iterable[Spec],
        *,
        convert_dir_literal_to_address_literal: bool,
        filter_by_global_options: bool = False,
        from_change_detection: bool = False,
    ) -> Specs:
        """Create from a heterogeneous iterable of Spec objects.

        If the `Spec` objects are already separated by type, prefer using the class's constructor
        directly.
        """
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
                if convert_dir_literal_to_address_literal:
                    address_literals.append(spec.to_address_literal())
                else:
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

    def __bool__(self) -> bool:
        return bool(
            self.address_literals
            or self.file_literals
            or self.file_globs
            or self.dir_literals
            or self.dir_globs
            or self.recursive_globs
            or self.ancestor_globs
        )

    def arguments_provided_description(self) -> str | None:
        """A description of what the user specified, e.g. 'target arguments'."""
        specs_descriptions = []
        if self.address_literals:
            specs_descriptions.append("target")
        if self.file_literals or self.file_globs:
            specs_descriptions.append("file")
        if self.dir_literals:
            specs_descriptions.append("directory")
        if self.dir_globs or self.recursive_globs or self.ancestor_globs:
            specs_descriptions.append("glob")

        if not specs_descriptions:
            return None
        if len(specs_descriptions) == 1:
            return f"{specs_descriptions[0]} arguments"
        if len(specs_descriptions) == 2:
            return " and ".join(specs_descriptions) + " arguments"
        return ", ".join(specs_descriptions[:-1]) + f", and {specs_descriptions[-1]} arguments"


@dataclass(frozen=True)
class SpecsWithoutFileOwners:
    """The subset of `Specs` that do not use the `Owners` rule to match targets.

    This exists to work around a cycle in the rule graph. Usually, consumers should use the simpler
    `Get(Addresses, Specs)`, which will result in this rule being used.
    """

    address_literals: tuple[AddressLiteralSpec, ...] = ()
    dir_globs: tuple[DirGlobSpec, ...] = ()
    recursive_globs: tuple[RecursiveGlobSpec, ...] = ()
    ancestor_globs: tuple[AncestorGlobSpec, ...] = ()

    filter_by_global_options: bool = False

    @classmethod
    def from_specs(cls, specs: Specs) -> SpecsWithoutFileOwners:
        return SpecsWithoutFileOwners(
            specs.address_literals,
            specs.dir_globs,
            specs.recursive_globs,
            specs.ancestor_globs,
            filter_by_global_options=specs.filter_by_global_options,
        )

    def glob_specs(self) -> Iterator[DirGlobSpec | RecursiveGlobSpec | AncestorGlobSpec]:
        yield from self.dir_globs
        yield from self.recursive_globs
        yield from self.ancestor_globs

    def to_build_file_path_globs(
        self, *, build_patterns: Iterable[str], build_ignore_patterns: Iterable[str]
    ) -> PathGlobs:
        includes: set[str] = set()
        for spec in (*self.dir_globs, *self.ancestor_globs):
            spec = cast("DirGlobSpec | AncestorGlobSpec", spec)
            includes.update(
                os.path.join(f, pattern)
                for pattern in build_patterns
                for f in recursive_dirname(spec.directory)
            )
        for recursive_spec in self.recursive_globs:
            for pattern in build_patterns:
                includes.update(
                    os.path.join(f, pattern) for f in recursive_dirname(recursive_spec.directory)
                )
                includes.add(os.path.join(recursive_spec.directory, "**", pattern))
        ignores = (f"!{p}" for p in build_ignore_patterns)
        return PathGlobs((*includes, *ignores))


@dataclass(frozen=True)
class SpecsWithOnlyFileOwners:
    """The subset of `Specs` that require using the `Owners` rule to match targets.

    This exists to work around a cycle in the rule graph. Usually, consumers should use the simpler
    `Get(Addresses, Specs)`, which will result in this rule being used.
    """

    file_literals: tuple[FileLiteralSpec, ...] = ()
    file_globs: tuple[FileGlobSpec, ...] = ()

    filter_by_global_options: bool = False

    @classmethod
    def from_specs(cls, specs: Specs) -> SpecsWithOnlyFileOwners:
        return SpecsWithOnlyFileOwners(
            specs.file_literals,
            specs.file_globs,
            filter_by_global_options=specs.filter_by_global_options,
        )

    @staticmethod
    def _generate_path_globs(
        specs: Iterable[FileLiteralSpec | FileGlobSpec],
        glob_match_error_behavior: GlobMatchErrorBehavior,
    ) -> PathGlobs:
        return PathGlobs(
            globs=(s.to_glob() for s in specs),
            glob_match_error_behavior=glob_match_error_behavior,
            # We validate that _every_ glob is valid.
            conjunction=GlobExpansionConjunction.all_match,
            description_of_origin=(
                None
                if glob_match_error_behavior == GlobMatchErrorBehavior.ignore
                else "file/directory arguments"
            ),
        )

    def path_globs_for_spec(
        self,
        spec: FileLiteralSpec | FileGlobSpec,
        glob_match_error_behavior: GlobMatchErrorBehavior,
    ) -> PathGlobs:
        """Generate PathGlobs for the specific spec."""
        return self._generate_path_globs([spec], glob_match_error_behavior)

    def to_path_globs(self, glob_match_error_behavior: GlobMatchErrorBehavior) -> PathGlobs:
        """Generate a single PathGlobs for the instance."""
        return self._generate_path_globs(self.all_specs(), glob_match_error_behavior)

    def all_specs(self) -> Iterator[FileLiteralSpec | FileGlobSpec]:
        yield from self.file_literals
        yield from self.file_globs

    def __bool__(self) -> bool:
        return bool(self.file_literals or self.file_globs)
