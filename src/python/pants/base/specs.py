# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import os
from abc import ABC, ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Iterable

from pants.base.glob_match_error_behavior import GlobMatchErrorBehavior
from pants.engine.fs import GlobExpansionConjunction, PathGlobs
from pants.util.dirutil import fast_relpath_optional, recursive_dirname
from pants.util.meta import frozen_after_init


class Spec(ABC):
    """A specification for what Pants should operate on."""

    @abstractmethod
    def __str__(self) -> str:
        """The normalized string representation of this spec."""


class AddressSpec(Spec, metaclass=ABCMeta):
    """Represents address selectors as passed from the command line."""


@dataclass(frozen=True)
class AddressLiteralSpec(AddressSpec):
    """An AddressSpec for a single address.

    This may be one of:

    * A traditional address, like `dir:lib`.
    * A generated target address like `dir:lib#generated` or `dir#generated`.
    * A file address using disambiguation syntax like dir/f.ext:lib` (files without a target will
      be FilesystemSpecs).
    """

    path_component: str
    target_component: str | None = None
    generated_component: str | None = None

    def __str__(self) -> str:
        tgt = f":{self.target_component}" if self.target_component else ""
        generated = f"#{self.generated_component}" if self.generated_component else ""
        return f"{self.path_component}{tgt}{generated}"

    @property
    def is_directory_shorthand(self) -> bool:
        """Is in the format `path/to/dir`, which is shorthand for `path/to/dir:dir`."""
        return self.target_component is None and self.generated_component is None


@dataclass(frozen=True)  # type: ignore[misc]
class AddressGlobSpec(AddressSpec, metaclass=ABCMeta):
    directory: str
    error_if_no_matches: ClassVar[bool]

    def to_build_file_globs(self, build_patterns: Iterable[str]) -> set[str]:
        """Generate glob patterns matching all the BUILD files this address spec must inspect to
        resolve the addresses.

        The default matches the directory's BUILD file and all ancestor directories, which is
        necessary to handle generated targets that may be defined in ancestor BUILD files.
        Subclasses can extend this default.
        """
        return {
            os.path.join(f, pattern)
            for pattern in build_patterns
            for f in recursive_dirname(self.directory)
        }

    @abstractmethod
    def matches(self, tgt_residence_dir: str) -> bool:
        """Does a target residing in `tgt_residence_dir` match the spec?"""


class SiblingAddresses(AddressGlobSpec):
    """An AddressSpec representing all addresses residing within the given directory.

    At least one such address must exist.
    """

    error_if_no_matches = True

    def __str__(self) -> str:
        return f"{self.directory}:"

    def matches(self, tgt_residence_dir: str) -> bool:
        return tgt_residence_dir == self.directory


class MaybeEmptySiblingAddresses(SiblingAddresses):
    """An AddressSpec representing all addresses residing within the given directory.

    It is not an error if there are no such addresses.
    """

    error_if_no_matches = False


class DescendantAddresses(AddressGlobSpec):
    """An AddressSpec representing all addresses residing recursively under the given directory.

    At least one such address must exist.
    """

    error_if_no_matches = True

    def __str__(self) -> str:
        return f"{self.directory}::"

    def to_build_file_globs(self, build_patterns: Iterable[str]) -> set[str]:
        return {
            *super().to_build_file_globs(build_patterns),
            *(os.path.join(self.directory, "**", pat) for pat in build_patterns),
        }

    def matches(self, tgt_residence_dir: str) -> bool:
        return fast_relpath_optional(tgt_residence_dir, self.directory) is not None


class MaybeEmptyDescendantAddresses(DescendantAddresses):
    """An AddressSpec representing all addresses residing recursively under the given directory.

    It is not an error if there are no such addresses.
    """

    error_if_no_matches = False


class AscendantAddresses(AddressGlobSpec):
    """An AddressSpec representing all addresses located recursively in and above the given
    directory."""

    error_if_no_matches = False

    def __str__(self) -> str:
        return f"{self.directory}^"

    def matches(self, tgt_residence_dir: str) -> bool:
        return fast_relpath_optional(self.directory, tgt_residence_dir) is not None


@frozen_after_init
@dataclass(unsafe_hash=True)
class AddressSpecs:
    literals: tuple[AddressLiteralSpec, ...]
    globs: tuple[AddressGlobSpec, ...]
    filter_by_global_options: bool

    def __init__(
        self, specs: Iterable[AddressSpec], *, filter_by_global_options: bool = False
    ) -> None:
        """Create the specs for what addresses Pants should run on.

        If `filter_by_global_options` is set to True, then the resulting Addresses will be filtered
        by the global options `--tag` and `--exclude-target-regexp`.
        """
        literals = []
        globs = []
        for spec in specs:
            if isinstance(spec, AddressLiteralSpec):
                literals.append(spec)
            elif isinstance(spec, AddressGlobSpec):
                globs.append(spec)
            else:
                raise ValueError(f"Unexpected type of AddressSpec: {repr(self)}")

        self.literals = tuple(literals)
        self.globs = tuple(globs)
        self.filter_by_global_options = filter_by_global_options

    @property
    def specs(self) -> tuple[AddressSpec, ...]:
        return (*self.literals, *self.globs)

    def to_build_file_path_globs(
        self, *, build_patterns: Iterable[str], build_ignore_patterns: Iterable[str]
    ) -> PathGlobs:
        includes = set(
            itertools.chain.from_iterable(
                spec.to_build_file_globs(build_patterns) for spec in self.globs
            )
        )
        ignores = (f"!{p}" for p in build_ignore_patterns)
        return PathGlobs(globs=(*includes, *ignores))

    def __bool__(self) -> bool:
        return bool(self.specs)


class FilesystemSpec(Spec, metaclass=ABCMeta):
    @abstractmethod
    def to_glob(self) -> str:
        """Convert to a glob understood by `PathGlobs`."""


@dataclass(frozen=True)
class FileLiteralSpec(FilesystemSpec):
    """A literal file name, e.g. `foo.py`."""

    file: str

    def __str__(self) -> str:
        return self.file

    def to_glob(self) -> str:
        return self.file


@dataclass(frozen=True)
class FileGlobSpec(FilesystemSpec):
    """A spec with a glob or globs, e.g. `*.py` and `**/*.java`."""

    glob: str

    def __str__(self) -> str:
        return self.glob

    def to_glob(self) -> str:
        return self.glob


@dataclass(frozen=True)
class FileIgnoreSpec(FilesystemSpec):
    """A spec to ignore certain files or globs."""

    glob: str

    def __post_init__(self) -> None:
        if self.glob.startswith("!"):
            raise ValueError(f"The `glob` for {self} should not start with `!`.")

    def __str__(self) -> str:
        return f"!{self.glob}"

    def to_glob(self) -> str:
        return f"!{self.glob}"


@dataclass(frozen=True)
class DirLiteralSpec(FilesystemSpec):
    """A literal dir path, e.g. `some/dir`.

    The empty string represents the build root.
    """

    v: str

    def __str__(self) -> str:
        return self.v

    def to_glob(self) -> str:
        if not self.v:
            return "*"
        return f"{self.v}/*"

    def to_address_literal(self) -> AddressLiteralSpec:
        """For now, `dir` can also be shorthand for `dir:dir`."""
        return AddressLiteralSpec(
            path_component=self.v, target_component=None, generated_component=None
        )


@frozen_after_init
@dataclass(unsafe_hash=True)
class FilesystemSpecs:
    file_includes: tuple[FileLiteralSpec | FileGlobSpec, ...]
    dir_includes: tuple[DirLiteralSpec, ...]
    ignores: tuple[FileIgnoreSpec, ...]

    def __init__(self, specs: Iterable[FilesystemSpec]) -> None:
        file_includes = []
        dir_includes = []
        ignores = []
        for spec in specs:
            if isinstance(spec, (FileLiteralSpec, FileGlobSpec)):
                file_includes.append(spec)
            elif isinstance(spec, DirLiteralSpec):
                dir_includes.append(spec)
            elif isinstance(spec, FileIgnoreSpec):
                ignores.append(spec)
            else:
                raise AssertionError(f"Unexpected type of FilesystemSpec: {repr(self)}")
        self.file_includes = tuple(file_includes)
        self.dir_includes = tuple(dir_includes)
        self.ignores = tuple(ignores)

    @staticmethod
    def _generate_path_globs(
        specs: Iterable[FilesystemSpec], glob_match_error_behavior: GlobMatchErrorBehavior
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
        spec: FileLiteralSpec | FileGlobSpec | DirLiteralSpec,
        glob_match_error_behavior: GlobMatchErrorBehavior,
    ) -> PathGlobs:
        """Generate PathGlobs for the specific spec, automatically including the instance's
        FileIgnoreSpecs."""
        return self._generate_path_globs((spec, *self.ignores), glob_match_error_behavior)

    def to_path_globs(self, glob_match_error_behavior: GlobMatchErrorBehavior) -> PathGlobs:
        """Generate a single PathGlobs for the instance."""
        return self._generate_path_globs(
            (*self.file_includes, *self.dir_includes, *self.ignores), glob_match_error_behavior
        )

    def __bool__(self) -> bool:
        return bool(self.file_includes) or bool(self.dir_includes) or bool(self.ignores)


@dataclass(frozen=True)
class Specs:
    address_specs: AddressSpecs
    filesystem_specs: FilesystemSpecs

    @property
    def provided(self) -> bool:
        """Did the user provide specs?"""
        return bool(self.address_specs) or bool(self.filesystem_specs)

    @classmethod
    def empty(cls) -> Specs:
        return Specs(AddressSpecs([], filter_by_global_options=True), FilesystemSpecs([]))
