# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar, Iterable, Iterator, cast

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
        params = ""
        if self.parameters:
            rhs = ",".join(f"{k}={v}" for k, v in self.parameters.items())
            params = f"@{rhs}"
        return f"{self.path_component}{tgt}{generated}{params}"

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

    matches_target_generators: ClassVar[bool] = False

    def __str__(self) -> str:
        return self.directory

    def to_address_literal(self) -> AddressLiteralSpec:
        """For now, `dir` can also be shorthand for `dir:dir`."""
        return AddressLiteralSpec(path_component=self.directory)

    def matches_target_residence_dir(self, residence_dir: str) -> bool:
        return residence_dir == self.directory

    def to_glob(self) -> str:
        return os.path.join(self.directory, "*")


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

    matches_target_generators: ClassVar[bool] = True

    def __str__(self) -> str:
        return f"{self.directory}:"

    def matches_target_residence_dir(self, residence_dir: str) -> bool:
        return residence_dir == self.directory

    def to_glob(self) -> str:
        return os.path.join(self.directory, "*")


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

    matches_target_generators: ClassVar[bool] = True

    def __str__(self) -> str:
        return f"{self.directory}::"

    def matches_target_residence_dir(self, residence_dir: str) -> bool:
        return fast_relpath_optional(residence_dir, self.directory) is not None

    def to_glob(self) -> str:
        return os.path.join(self.directory, "**")


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

    matches_target_generators: ClassVar[bool] = True

    def __str__(self) -> str:
        return f"{self.directory}^"

    def matches_target_residence_dir(self, residence_dir: str) -> bool:
        return fast_relpath_optional(self.directory, residence_dir) is not None


def _create_path_globs(
    globs: Iterable[str],
    unmatched_glob_behavior: GlobMatchErrorBehavior,
    *,
    description_of_origin: str,
) -> PathGlobs:
    return PathGlobs(
        globs=globs,
        glob_match_error_behavior=unmatched_glob_behavior,
        # We validate that _every_ glob is valid.
        conjunction=GlobExpansionConjunction.all_match,
        description_of_origin=(
            None
            if unmatched_glob_behavior == GlobMatchErrorBehavior.ignore
            else description_of_origin
        ),
    )


@dataclass(frozen=True)
class RawSpecs:
    """Convert the specs into matching targets and files.

    Unlike `Specs`, this does not consider include vs. ignore specs. It simply matches all relevant
    targets/files.

    When you want to operate on what the user specified, use `Specs`. Otherwise, you can use
    either `Specs` or `RawSpecs` in rules, e.g. to find what targets exist in a directory.
    """

    description_of_origin: str

    address_literals: tuple[AddressLiteralSpec, ...] = ()
    file_literals: tuple[FileLiteralSpec, ...] = ()
    file_globs: tuple[FileGlobSpec, ...] = ()
    dir_literals: tuple[DirLiteralSpec, ...] = ()
    dir_globs: tuple[DirGlobSpec, ...] = ()
    recursive_globs: tuple[RecursiveGlobSpec, ...] = ()
    ancestor_globs: tuple[AncestorGlobSpec, ...] = ()

    unmatched_glob_behavior: GlobMatchErrorBehavior = GlobMatchErrorBehavior.error
    filter_by_global_options: bool = False
    from_change_detection: bool = False

    @classmethod
    def create(
        cls,
        specs: Iterable[Spec],
        *,
        description_of_origin: str,
        convert_dir_literal_to_address_literal: bool,
        unmatched_glob_behavior: GlobMatchErrorBehavior = GlobMatchErrorBehavior.error,
        filter_by_global_options: bool = False,
        from_change_detection: bool = False,
    ) -> RawSpecs:
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
        return RawSpecs(
            address_literals=tuple(address_literals),
            file_literals=tuple(file_literals),
            file_globs=tuple(file_globs),
            dir_literals=tuple(dir_literals),
            dir_globs=tuple(dir_globs),
            recursive_globs=tuple(recursive_globs),
            ancestor_globs=tuple(ancestor_globs),
            description_of_origin=description_of_origin,
            unmatched_glob_behavior=unmatched_glob_behavior,
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

    def to_specs_paths_path_globs(self) -> PathGlobs:
        """`PathGlobs` to find all files from the specs, independent of targets."""
        relevant_specs: Iterable[
            FileLiteralSpec | FileGlobSpec | DirLiteralSpec | DirGlobSpec | RecursiveGlobSpec
        ] = (
            *self.file_literals,
            *self.file_globs,
            *self.dir_literals,
            *self.dir_globs,
            *self.recursive_globs,
        )
        return _create_path_globs(
            (spec.to_glob() for spec in relevant_specs),
            (
                GlobMatchErrorBehavior.ignore
                if self.from_change_detection
                else self.unmatched_glob_behavior
            ),
            description_of_origin=self.description_of_origin,
        )


@dataclass(frozen=True)
class RawSpecsWithoutFileOwners:
    """The subset of `RawSpecs` that do not use the `Owners` rule to match targets.

    This exists to work around a cycle in the rule graph. Usually, consumers should use the simpler
    `Get(Addresses, RawSpecs)`, which will result in this rule being used.
    """

    description_of_origin: str

    address_literals: tuple[AddressLiteralSpec, ...] = ()
    dir_literals: tuple[DirLiteralSpec, ...] = ()
    dir_globs: tuple[DirGlobSpec, ...] = ()
    recursive_globs: tuple[RecursiveGlobSpec, ...] = ()
    ancestor_globs: tuple[AncestorGlobSpec, ...] = ()

    unmatched_glob_behavior: GlobMatchErrorBehavior = GlobMatchErrorBehavior.error
    filter_by_global_options: bool = False

    @classmethod
    def from_raw_specs(cls, specs: RawSpecs) -> RawSpecsWithoutFileOwners:
        return RawSpecsWithoutFileOwners(
            address_literals=specs.address_literals,
            dir_literals=specs.dir_literals,
            dir_globs=specs.dir_globs,
            recursive_globs=specs.recursive_globs,
            ancestor_globs=specs.ancestor_globs,
            description_of_origin=specs.description_of_origin,
            unmatched_glob_behavior=specs.unmatched_glob_behavior,
            filter_by_global_options=specs.filter_by_global_options,
        )

    def glob_specs(
        self,
    ) -> Iterator[DirLiteralSpec | DirGlobSpec | RecursiveGlobSpec | AncestorGlobSpec]:
        yield from self.dir_literals
        yield from self.dir_globs
        yield from self.recursive_globs
        yield from self.ancestor_globs

    def to_build_file_path_globs_tuple(
        self, *, build_patterns: Iterable[str], build_ignore_patterns: Iterable[str]
    ) -> tuple[PathGlobs, PathGlobs]:
        """Returns `PathGlobs` for the actual BUILD files, along with another solely used to
        validate that the directories exist.

        The second `PathGlobs` is necessary so that we can error on directories that don't actually
        exist, yet we don't error if the directory simply has no targets. See
        https://github.com/pantsbuild/pants/issues/15558.
        """
        build_includes: set[str] = set()
        validation_includes: set[str] = set()
        for spec in (*self.dir_literals, *self.dir_globs, *self.ancestor_globs):
            spec = cast("DirLiteralSpec | DirGlobSpec | AncestorGlobSpec", spec)
            validation_includes.add(
                spec.to_glob()
                if isinstance(spec, (DirLiteralSpec, DirGlobSpec))
                else os.path.join(spec.directory, "*")
            )
            build_includes.update(
                os.path.join(f, pattern)
                for pattern in build_patterns
                for f in recursive_dirname(spec.directory)
            )

        for recursive_spec in self.recursive_globs:
            validation_includes.add(recursive_spec.to_glob())
            for pattern in build_patterns:
                build_includes.update(
                    os.path.join(f, pattern) for f in recursive_dirname(recursive_spec.directory)
                )
                build_includes.add(os.path.join(recursive_spec.directory, "**", pattern))

        ignores = (f"!{p}" for p in build_ignore_patterns)
        build_path_globs = PathGlobs((*build_includes, *ignores))
        validation_path_globs = (
            PathGlobs(())
            if self.unmatched_glob_behavior == GlobMatchErrorBehavior.ignore
            else _create_path_globs(
                (*validation_includes, *ignores),
                self.unmatched_glob_behavior,
                description_of_origin=self.description_of_origin,
            )
        )
        return build_path_globs, validation_path_globs


@dataclass(frozen=True)
class RawSpecsWithOnlyFileOwners:
    """The subset of `RawSpecs` that require using the `Owners` rule to match targets.

    This exists to work around a cycle in the rule graph. Usually, consumers should use the simpler
    `Get(Addresses, RawSpecs)`, which will result in this rule being used.
    """

    description_of_origin: str

    file_literals: tuple[FileLiteralSpec, ...] = ()
    file_globs: tuple[FileGlobSpec, ...] = ()

    unmatched_glob_behavior: GlobMatchErrorBehavior = GlobMatchErrorBehavior.error
    filter_by_global_options: bool = False
    from_change_detection: bool = False

    @classmethod
    def from_raw_specs(cls, specs: RawSpecs) -> RawSpecsWithOnlyFileOwners:
        return RawSpecsWithOnlyFileOwners(
            description_of_origin=specs.description_of_origin,
            file_literals=specs.file_literals,
            file_globs=specs.file_globs,
            unmatched_glob_behavior=specs.unmatched_glob_behavior,
            filter_by_global_options=specs.filter_by_global_options,
            from_change_detection=specs.from_change_detection,
        )

    def path_globs_for_spec(self, spec: FileLiteralSpec | FileGlobSpec) -> PathGlobs:
        """Generate PathGlobs for the specific spec."""
        unmatched_glob_behavior = (
            GlobMatchErrorBehavior.ignore
            if self.from_change_detection
            else self.unmatched_glob_behavior
        )
        return _create_path_globs(
            (spec.to_glob(),),
            unmatched_glob_behavior,
            description_of_origin=self.description_of_origin,
        )

    def all_specs(self) -> Iterator[FileLiteralSpec | FileGlobSpec]:
        yield from self.file_literals
        yield from self.file_globs

    def __bool__(self) -> bool:
        return bool(self.file_literals or self.file_globs)


@dataclass(frozen=True)
class Specs:
    """The specs provided by the user for what to run on.

    The `ignores` will filter out all relevant `includes`.

    If your rule does not need to consider includes vs. ignores, e.g. to find all targets in a
    directory,  you can directly use `RawSpecs`.
    """

    includes: RawSpecs
    ignores: RawSpecs

    def __bool__(self) -> bool:
        return bool(self.includes) or bool(self.ignores)

    @classmethod
    def empty(self) -> Specs:
        return Specs(
            RawSpecs(description_of_origin="<not used>"),
            RawSpecs(description_of_origin="<not used>"),
        )

    def arguments_provided_description(self) -> str | None:
        """A description of what the user specified, e.g. 'target arguments'."""
        specs_descriptions = []
        if self.includes.address_literals or self.ignores.address_literals:
            specs_descriptions.append("target")
        if (
            self.includes.file_literals
            or self.includes.file_globs
            or self.ignores.file_literals
            or self.ignores.file_globs
        ):
            specs_descriptions.append("file")
        if self.includes.dir_literals or self.ignores.dir_literals:
            specs_descriptions.append("directory")
        if (
            self.includes.dir_globs
            or self.includes.recursive_globs
            or self.includes.ancestor_globs
            or self.ignores.dir_globs
            or self.ignores.recursive_globs
            or self.ignores.ancestor_globs
        ):
            specs_descriptions.append("glob")

        if not specs_descriptions:
            return None
        if len(specs_descriptions) == 1:
            return f"{specs_descriptions[0]} arguments"
        if len(specs_descriptions) == 2:
            return " and ".join(specs_descriptions) + " arguments"
        return ", ".join(specs_descriptions[:-1]) + f", and {specs_descriptions[-1]} arguments"
