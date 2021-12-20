# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import itertools
import os
from abc import ABCMeta
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Iterator, Mapping, Optional, cast

from pants.base.specs import (
    AddressSpecs,
    AscendantAddresses,
    MaybeEmptyDescendantAddresses,
    Spec,
    Specs,
)
from pants.build_graph.address import Address
from pants.core.util_rules import pants_bin
from pants.core.util_rules.pants_bin import PantsBin
from pants.engine.collection import DeduplicatedCollection
from pants.engine.console import Console
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    PathGlobs,
    Paths,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import (
    SourcesField,
    SourcesPaths,
    SourcesPathsRequest,
    Target,
    UnexpandedTargets,
)
from pants.engine.unions import UnionMembership, union
from pants.source.filespec import Filespec, matches_filespec
from pants.util.docutil import doc_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized
from pants.util.meta import frozen_after_init


@union
@dataclass(frozen=True)
class PutativeTargetsRequest(metaclass=ABCMeta):
    search_paths: PutativeTargetsSearchPaths


@dataclass(frozen=True)
class PutativeTargetsSearchPaths:
    dirs: tuple[str, ...]

    def path_globs(self, filename_glob: str) -> PathGlobs:
        return PathGlobs([os.path.join(d, "**", filename_glob) for d in self.dirs])


@memoized
def default_sources_for_target_type(tgt_type: type[Target]) -> tuple[str, ...]:
    for field in tgt_type.core_fields:
        if issubclass(field, SourcesField):
            return field.default or tuple()
    return tuple()


@frozen_after_init
@dataclass(order=True, unsafe_hash=True)
class PutativeTarget:
    """A potential target to add, detected by various heuristics.

    This class uses the term "target" in the loose sense. It can also represent an invocation of a
    target-generating macro.
    """

    # Note that field order is such that the dataclass order will be by address (path+name).
    path: str
    name: str
    type_alias: str

    # The sources that triggered creating of this putative target.
    # The putative target will own these sources, but may also glob over other sources.
    # If the putative target does not have a `sources` field, then this value must be the
    # empty tuple.
    triggering_sources: tuple[str, ...]

    # The globs of sources owned by this target.
    # If kwargs contains an explicit sources key, it should be identical to this value.
    # Otherwise, this field should contain the default globs that the target type will apply.
    # If the putative target does not have a `sources` field, then this value must be the
    # empty tuple.
    # TODO: If target_type is a regular target (and not a macro) we can derive the default
    #  source globs for that type from BuildConfiguration.  However that is fiddly and not
    #  a high priority.
    owned_sources: tuple[str, ...]

    # Whether the pututative target has an address (or, e.g., is a macro with no address).
    addressable: bool

    # Note that we generate the BUILD file target entry from these kwargs, the
    # `name`, and `type_alias`.
    kwargs: FrozenDict[str, str | int | bool | tuple[str, ...]]

    # Any comment lines to add above the BUILD file stanza we generate for this putative target.
    # Should include the `#` prefix, which will not be added.
    comments: tuple[str, ...]

    @classmethod
    def for_target_type(
        cls,
        target_type: type[Target],
        path: str,
        name: str | None,
        triggering_sources: Iterable[str],
        kwargs: Mapping[str, str | int | bool | tuple[str, ...]] | None = None,
        comments: Iterable[str] = tuple(),
    ) -> PutativeTarget:
        if name is None:
            name = os.path.basename(path)

        explicit_sources = (kwargs or {}).get("sources")
        if explicit_sources is not None and not isinstance(explicit_sources, tuple):
            raise TypeError(
                "Explicit sources passed to PutativeTarget.for_target_type must be a Tuple[str]."
            )

        default_sources = default_sources_for_target_type(target_type)
        if (explicit_sources or triggering_sources) and not default_sources:
            raise AssertionError(
                f"A target of type {target_type.__name__} was proposed at "
                f"address {path}:{name} with explicit sources {', '.join(explicit_sources or triggering_sources)}, "
                "but this target type does not have a `sources` field."
            )
        owned_sources = explicit_sources or default_sources or tuple()
        return cls(
            path,
            name,
            target_type.alias,
            triggering_sources,
            owned_sources,
            addressable=True,  # "Real" targets are always addressable.
            kwargs=kwargs,
            comments=comments,
        )

    def __init__(
        self,
        path: str,
        name: str,
        type_alias: str,
        triggering_sources: Iterable[str],
        owned_sources: Iterable[str],
        *,
        addressable: bool = True,
        kwargs: Mapping[str, str | int | bool | tuple[str, ...]] | None = None,
        comments: Iterable[str] = tuple(),
    ) -> None:
        self.path = path
        self.name = name
        self.type_alias = type_alias
        self.triggering_sources = tuple(triggering_sources)
        self.owned_sources = tuple(owned_sources)
        self.addressable = addressable
        self.kwargs = FrozenDict(kwargs or {})
        self.comments = tuple(comments)

    @property
    def address(self) -> Address:
        if not self.addressable:
            raise ValueError(
                f"Cannot compute address for non-addressable putative target of type "
                f"{self.type_alias} at path {self.path}"
            )
        return Address(self.path, target_name=self.name)

    def realias(self, new_alias: str | None) -> PutativeTarget:
        """A copy of this object with the alias replaced to the given alias.

        Returns this object if the alias is None or is identical to this objects existing alias.
        """
        return (
            self
            if (new_alias is None or new_alias == self.type_alias)
            else dataclasses.replace(self, type_alias=new_alias)
        )

    def rename(self, new_name: str) -> PutativeTarget:
        """A copy of this object with the name replaced to the given name."""
        return dataclasses.replace(self, name=new_name)

    def restrict_sources(self) -> PutativeTarget:
        """A copy of this object with the sources explicitly set to just the triggering sources."""
        owned_sources = self.triggering_sources
        return dataclasses.replace(
            self,
            owned_sources=owned_sources,
            kwargs={**self.kwargs, "sources": owned_sources},
        )

    def add_comments(self, comments: Iterable[str]) -> PutativeTarget:
        return dataclasses.replace(self, comments=self.comments + tuple(comments))

    def generate_build_file_stanza(self, indent: str) -> str:
        def fmt_val(v) -> str:
            if isinstance(v, str):
                return f'"{v}"'
            if isinstance(v, tuple):
                val_parts = [f"\n{indent*2}{fmt_val(x)}" for x in v]
                val_str = ",".join(val_parts) + ("," if v else "")
                return f"[{val_str}\n{indent}]"
            return repr(v)

        is_default_name = self.name == os.path.basename(self.path)
        if self.kwargs or not is_default_name:
            _kwargs = {
                **({} if is_default_name else {"name": self.name}),
                **self.kwargs,  # type: ignore[arg-type]
            }
            _kwargs_str_parts = [f"\n{indent}{k}={fmt_val(v)}" for k, v in _kwargs.items()]
            kwargs_str = ",".join(_kwargs_str_parts) + ",\n"
        else:
            kwargs_str = ""

        comment_str = ("\n".join(self.comments) + "\n") if self.comments else ""
        return f"{comment_str}{self.type_alias}({kwargs_str})\n"


class PutativeTargets(DeduplicatedCollection[PutativeTarget]):
    sort_input = True

    @classmethod
    def merge(cls, tgts_iters: Iterable[PutativeTargets]) -> PutativeTargets:
        all_tgts: list[PutativeTarget] = []
        for tgts in tgts_iters:
            all_tgts.extend(tgts)
        return cls(all_tgts)


class TailorSubsystem(GoalSubsystem):
    name = "tailor"
    help = "Auto-generate BUILD file targets for new source files."

    required_union_implementations = (PutativeTargetsRequest,)

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--check",
            type=bool,
            default=False,
            help=(
                "Do not write changes to disk, only write back what would change. Return code "
                "0 means there would be no changes, and 1 means that there would be. "
            ),
        )

        register(
            "--build-file-name",
            advanced=True,
            type=str,
            default="BUILD",
            help=(
                "The name to use for generated BUILD files.\n\n"
                "This must be compatible with `[GLOBAL].build_patterns`."
            ),
        )
        register(
            "--build-file-header",
            advanced=True,
            type=str,
            default=None,
            help="A header, e.g., a copyright notice, to add to the content of created BUILD files.",
        )
        register(
            "--build-file-indent",
            advanced=True,
            type=str,
            default="    ",
            help="The indent to use when auto-editing BUILD files.",
        )

        register(
            "--alias-mapping",
            advanced=True,
            type=dict,
            help="A mapping from standard target type to custom type to use instead. The custom "
            "type can be a custom target type or a macro that offers compatible functionality "
            f"to the one it replaces (see {doc_url('macros')}).",
        )

        register(
            "--ignore-paths",
            advanced=True,
            type=list,
            member_type=str,
            help=(
                "Do not edit or create BUILD files at these paths.\n\n"
                "Can use literal file names and/or globs, e.g. "
                "`['project/BUILD, 'ignore_me/**']`.\n\n"
                "This augments the option `[GLOBAL].build_ignore`, which tells Pants to also not "
                "_read_ BUILD files at certain paths. In contrast, this option only tells Pants to "
                "not edit/create BUILD files at the specified paths."
            ),
        )
        register(
            "--ignore-adding-targets",
            advanced=True,
            type=list,
            member_type=str,
            help=(
                "Do not add these target definitions.\n\n"
                "Expects a list of target addresses that would normally be added by `tailor`, "
                "e.g. [`project:tgt']`. To find these names, you can run `tailor --check`, then "
                "combine the BUILD file path with the target's name. For example, if `tailor` "
                "would add the target `bin` to `project/BUILD`, then the address would be "
                "`project:bin`. If the BUILD file is at the root of your repository, use `//` for "
                "the path, e.g. `//:bin`.\n\n"
                "Does not work with macros."
            ),
        )

    @property
    def check(self) -> bool:
        return cast(bool, self.options.check)

    @property
    def build_file_name(self) -> str:
        return cast(str, self.options.build_file_name)

    @property
    def build_file_header(self) -> str | None:
        return cast(Optional[str], self.options.build_file_header)

    @property
    def build_file_indent(self) -> str:
        return cast(str, self.options.build_file_indent)

    @property
    def ignore_paths(self) -> tuple[str, ...]:
        return tuple(self.options.ignore_paths)

    @property
    def ignore_adding_targets(self) -> set[str]:
        return set(self.options.ignore_adding_targets)

    def alias_for(self, standard_type: str) -> str | None:
        # The get() could return None, but casting to str | None errors.
        # This cast suffices to avoid typecheck errors.
        return cast(str, self.options.alias_mapping.get(standard_type))

    def validate_build_file_name(self, build_file_patterns: tuple[str, ...]) -> None:
        """Check that the specified BUILD file name works with the repository's BUILD file
        patterns."""
        filespec = Filespec(includes=list(build_file_patterns))
        if not bool(matches_filespec(filespec, paths=[self.build_file_name])):
            raise ValueError(
                f"The option `[{self.options_scope}].build_file_name` is set to "
                f"`{self.build_file_name}`, which is not compatible with "
                f"`[GLOBAL].build_patterns`: {sorted(build_file_patterns)}. This means that "
                "generated BUILD files would be ignored.\n\n"
                "To fix, please update the options so that they are compatible."
            )

    def filter_by_ignores(
        self, putative_targets: Iterable[PutativeTarget], build_file_ignores: tuple[str, ...]
    ) -> Iterator[PutativeTarget]:
        ignore_paths_filespec = Filespec(includes=[*self.ignore_paths, *build_file_ignores])
        for ptgt in putative_targets:
            is_ignored_file = bool(
                matches_filespec(
                    ignore_paths_filespec,
                    paths=[os.path.join(ptgt.path, self.build_file_name)],
                )
            )
            if is_ignored_file:
                continue
            if ptgt.addressable:
                # Note that `tailor` can only generate explicit targets, so we don't need to
                # worry about generated address syntax (`#`) or file address syntax.
                address = f"{ptgt.path or '//'}:{ptgt.name}"
                if address in self.ignore_adding_targets:
                    continue
            yield ptgt


class TailorGoal(Goal):
    subsystem_cls = TailorSubsystem


def group_by_dir(paths: Iterable[str]) -> dict[str, set[str]]:
    """For a list of file paths, returns a dict of directory path -> files in that dir."""
    ret = defaultdict(set)
    for path in paths:
        dirname, filename = os.path.split(path)
        ret[dirname].add(filename)
    return ret


def group_by_build_file(
    build_file_name: str, ptgts: Iterable[PutativeTarget]
) -> dict[str, list[PutativeTarget]]:
    ret = defaultdict(list)
    for ptgt in ptgts:
        ret[os.path.join(ptgt.path, build_file_name)].append(ptgt)
    return ret


class AllOwnedSources(DeduplicatedCollection[str]):
    """All files in the project already owned by targets."""


@rule(desc="Determine all files already owned by targets", level=LogLevel.DEBUG)
async def determine_all_owned_sources() -> AllOwnedSources:
    all_tgts = await Get(UnexpandedTargets, AddressSpecs([MaybeEmptyDescendantAddresses("")]))
    all_sources_paths = await MultiGet(
        Get(SourcesPaths, SourcesPathsRequest(tgt.get(SourcesField))) for tgt in all_tgts
    )
    return AllOwnedSources(
        itertools.chain.from_iterable(sources_paths.files for sources_paths in all_sources_paths)
    )


@dataclass(frozen=True)
class UniquelyNamedPutativeTargets:
    """Putative targets that have no name conflicts with existing targets (or each other)."""

    putative_targets: PutativeTargets


@rule
async def rename_conflicting_targets(ptgts: PutativeTargets) -> UniquelyNamedPutativeTargets:
    """Ensure that no target addresses collide."""
    all_existing_tgts = await Get(
        UnexpandedTargets, AddressSpecs([MaybeEmptyDescendantAddresses("")])
    )
    existing_addrs: set[str] = {tgt.address.spec for tgt in all_existing_tgts}
    uniquely_named_putative_targets: list[PutativeTarget] = []
    for ptgt in ptgts:
        if not ptgt.addressable:
            # Non-addressable PutativeTargets never have collision issues.
            uniquely_named_putative_targets.append(ptgt)
            continue

        idx = 0
        possibly_renamed_ptgt = ptgt
        # Targets in root-level BUILD files must be named explicitly.
        if possibly_renamed_ptgt.path == "" and possibly_renamed_ptgt.kwargs.get("name") is None:
            possibly_renamed_ptgt = possibly_renamed_ptgt.rename("root")
        # Eliminate any address collisions.
        while possibly_renamed_ptgt.address.spec in existing_addrs:
            possibly_renamed_ptgt = ptgt.rename(f"{ptgt.name}{idx}")
            idx += 1
        uniquely_named_putative_targets.append(possibly_renamed_ptgt)
        existing_addrs.add(possibly_renamed_ptgt.address.spec)

    return UniquelyNamedPutativeTargets(PutativeTargets(uniquely_named_putative_targets))


@dataclass(frozen=True)
class DisjointSourcePutativeTarget:
    """Putative target whose sources don't overlap with those of any existing targets."""

    putative_target: PutativeTarget


@rule
async def restrict_conflicting_sources(ptgt: PutativeTarget) -> DisjointSourcePutativeTarget:
    source_paths = await Get(
        Paths,
        PathGlobs(
            SourcesField.prefix_glob_with_dirpath(ptgt.path, glob) for glob in ptgt.owned_sources
        ),
    )
    source_path_set = set(source_paths.files)
    source_dirs = {os.path.dirname(path) for path in source_path_set}
    possible_owners = await Get(
        UnexpandedTargets, AddressSpecs(AscendantAddresses(d) for d in source_dirs)
    )
    possible_owners_sources = await MultiGet(
        Get(SourcesPaths, SourcesPathsRequest(t.get(SourcesField))) for t in possible_owners
    )
    conflicting_targets = []
    for tgt, sources in zip(possible_owners, possible_owners_sources):
        if source_path_set.intersection(sources.files):
            conflicting_targets.append(tgt)

    if conflicting_targets:
        conflicting_addrs = sorted(tgt.address.spec for tgt in conflicting_targets)
        explicit_srcs_str = ", ".join(ptgt.kwargs.get("sources") or [])  # type: ignore[arg-type]
        orig_sources_str = (
            f"[{explicit_srcs_str}]" if explicit_srcs_str else f"the default for {ptgt.type_alias}"
        )
        ptgt = ptgt.restrict_sources().add_comments(
            [f"# NOTE: Sources restricted from {orig_sources_str} due to conflict with"]
            + [f"#   - {caddr}" for caddr in conflicting_addrs]
        )
    return DisjointSourcePutativeTarget(ptgt)


@dataclass(frozen=True)
class EditBuildFilesRequest:
    putative_targets: PutativeTargets


@dataclass(frozen=True)
class EditedBuildFiles:
    digest: Digest
    created_paths: tuple[str, ...]
    updated_paths: tuple[str, ...]


def make_content_str(
    existing_content: str | None, indent: str, pts: Iterable[PutativeTarget]
) -> str:
    new_content = ([] if existing_content is None else [existing_content]) + [
        pt.generate_build_file_stanza(indent) for pt in pts
    ]
    new_content = [s.rstrip() for s in new_content]
    return "\n\n".join(new_content) + "\n"


@rule(desc="Edit BUILD files with new targets", level=LogLevel.DEBUG)
async def edit_build_files(
    req: EditBuildFilesRequest, tailor_subsystem: TailorSubsystem
) -> EditedBuildFiles:
    ptgts_by_build_file = group_by_build_file(
        tailor_subsystem.build_file_name, req.putative_targets
    )
    # There may be an existing *directory* whose name collides with that of a BUILD file
    # we want to create. This is more likely on a system with case-insensitive paths,
    # such as MacOS. We detect such cases and use an alt BUILD file name to fix.
    existing_paths = await Get(Paths, PathGlobs(ptgts_by_build_file.keys()))
    existing_dirs = set(existing_paths.dirs)
    # Technically there could be a dir named "BUILD.pants" as well, but that's pretty unlikely.
    ptgts_by_build_file = {
        (f"{bf}.pants" if bf in existing_dirs else bf): pts
        for bf, pts in ptgts_by_build_file.items()
    }
    existing_build_files_contents = await Get(DigestContents, PathGlobs(ptgts_by_build_file.keys()))
    existing_build_files_contents_by_path = {
        ebfc.path: ebfc.content for ebfc in existing_build_files_contents
    }

    def make_content(bf_path: str, pts: Iterable[PutativeTarget]) -> FileContent:
        existing_content_bytes = existing_build_files_contents_by_path.get(bf_path)
        existing_content = (
            tailor_subsystem.build_file_header
            if existing_content_bytes is None
            else existing_content_bytes.decode()
        )
        new_content_bytes = make_content_str(
            existing_content, tailor_subsystem.build_file_indent, pts
        ).encode()
        return FileContent(bf_path, new_content_bytes)

    new_digest = await Get(
        Digest,
        CreateDigest([make_content(path, ptgts) for path, ptgts in ptgts_by_build_file.items()]),
    )

    updated = set(existing_build_files_contents_by_path.keys())
    created = set(ptgts_by_build_file.keys()) - updated
    return EditedBuildFiles(new_digest, tuple(sorted(created)), tuple(sorted(updated)))


def specs_to_dirs(specs: Specs) -> tuple[str, ...]:
    """Extract cmd-line specs that look like directories.

    Error on all other specs.

    This is a hack that allows us to emulate "directory specs" while we deprecate the shorthand of
    `dir` being `dir:dir`.
    """
    dir_specs = [dir_spec.v for dir_spec in specs.filesystem_specs.dir_includes]
    other_specs: list[Spec] = [
        *specs.filesystem_specs.file_includes,
        *specs.filesystem_specs.ignores,
        *specs.address_specs.globs,
    ]
    for spec in specs.address_specs.literals:
        if spec.is_directory_shorthand:
            dir_specs.append(spec.path_component)
        else:
            other_specs.append(spec)
    if other_specs:
        raise ValueError(
            "The tailor goal only accepts literal directories as arguments, but you "
            f"specified: {', '.join(str(spec) for spec in other_specs)}.  You can also "
            "specify no arguments to run against the entire repository."
        )
    # No specs at all means search the entire repo.
    return tuple(dir_specs) or ("",)


@goal_rule
async def tailor(
    tailor_subsystem: TailorSubsystem,
    console: Console,
    workspace: Workspace,
    union_membership: UnionMembership,
    specs: Specs,
    build_file_options: BuildFileOptions,
    pants_bin: PantsBin,
) -> TailorGoal:
    tailor_subsystem.validate_build_file_name(build_file_options.patterns)

    search_paths = PutativeTargetsSearchPaths(specs_to_dirs(specs))
    putative_targets_results = await MultiGet(
        Get(PutativeTargets, PutativeTargetsRequest, req_type(search_paths))
        for req_type in union_membership[PutativeTargetsRequest]
    )
    putative_targets = PutativeTargets.merge(putative_targets_results)
    putative_targets = PutativeTargets(
        pt.realias(tailor_subsystem.alias_for(pt.type_alias)) for pt in putative_targets
    )
    fixed_names_ptgts = await Get(UniquelyNamedPutativeTargets, PutativeTargets, putative_targets)
    fixed_sources_ptgts = await MultiGet(
        Get(DisjointSourcePutativeTarget, PutativeTarget, ptgt)
        for ptgt in fixed_names_ptgts.putative_targets
    )

    valid_putative_targets = list(
        tailor_subsystem.filter_by_ignores(
            (disjoint_source_ptgt.putative_target for disjoint_source_ptgt in fixed_sources_ptgts),
            build_file_options.ignores,
        )
    )
    if not valid_putative_targets:
        return TailorGoal(exit_code=0)

    edited_build_files = await Get(
        EditedBuildFiles, EditBuildFilesRequest(PutativeTargets(valid_putative_targets))
    )
    if not tailor_subsystem.check:
        workspace.write_digest(edited_build_files.digest)

    updated_build_files = set(edited_build_files.updated_paths)
    ptgts_by_build_file = group_by_build_file(
        tailor_subsystem.build_file_name, valid_putative_targets
    )
    for build_file_path, ptgts in ptgts_by_build_file.items():
        formatted_changes = "\n".join(
            (
                f"  - Add {console.green(ptgt.type_alias)} target {console.cyan(ptgt.name)}"
                if ptgt.addressable
                else f"  - Add macro {console.green(ptgt.type_alias)}"
            )
            for ptgt in ptgts
        )
        if build_file_path in updated_build_files:
            verb = "Would update" if tailor_subsystem.check else "Updated"
        else:
            verb = "Would create" if tailor_subsystem.check else "Created"
        console.print_stdout(f"{verb} {console.blue(build_file_path)}:\n{formatted_changes}")

    if tailor_subsystem.check:
        console.print_stdout(f"\nTo fix `tailor` failures, run `{pants_bin.name} tailor`.")

    return TailorGoal(exit_code=1 if tailor_subsystem.check else 0)


def rules():
    return (*collect_rules(), *pants_bin.rules())
