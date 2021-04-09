# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import itertools
import os
from abc import ABCMeta
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Set, Tuple, Type, cast

from pants.base.specs import AddressSpecs, AscendantAddresses, MaybeEmptyDescendantAddresses
from pants.build_graph.address import Address
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
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import (
    Sources,
    SourcesPaths,
    SourcesPathsRequest,
    Target,
    UnexpandedTargets,
)
from pants.engine.unions import UnionMembership, union
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized
from pants.util.meta import frozen_after_init


@union
class PutativeTargetsRequest(metaclass=ABCMeta):
    pass


@memoized
def default_sources_for_target_type(tgt_type: Type[Target]) -> Tuple[str, ...]:
    for field in tgt_type.core_fields:
        if issubclass(field, Sources):
            return field.default or tuple()
    raise ValueError(f"Target type {tgt_type.__name__} does not have a sources field.")


@frozen_after_init
@dataclass(order=True, unsafe_hash=True)
class PutativeTarget:
    """A potential target to add, detected by various heuristics."""

    # Note that field order is such that the dataclass order will be by address (path+name).
    path: str
    name: str
    type_alias: str

    # The sources that triggered creating of this putative target.
    # The putative target will own these sources, but may also glob over other sources.
    triggering_sources: Tuple[str, ...]

    # The globs of sources owned by this target.
    # If kwargs contains an explicit sources key, it should be identical to this value.
    # Otherwise, this field should contain the default globs that the target type will apply.
    # TODO: If target_type is a regular target (and not a macro) we can derive the default
    #  source globs for that type from BuildConfiguration.  However that is fiddly and not
    #  a high priority.
    owned_sources: Tuple[str, ...]

    # Note that we generate the BUILD file target entry exclusively from these kwargs (plus the
    # type_alias), not from the fields above, which are broken out for other uses.
    # This allows the creator of instances of this class to control whether the generated
    # target should assume default kwarg values or provide them explicitly.
    kwargs: FrozenDict[str, str | int | bool | Tuple[str, ...]]

    # Any comment lines to add above the BUILD file stanza we generate for this putative target.
    # Should include the `#` prefix, which will not be added.
    comments: Tuple[str, ...]

    # The name of the BUILD file to generate this putative target in. Typically just `BUILD`,
    # but `BUILD.suffix` for any suffix is also valid.
    build_file_name: str

    @classmethod
    def for_target_type(
        cls,
        target_type: Type[Target],
        path: str,
        name: str,
        triggering_sources: Iterable[str],
        kwargs: Mapping[str, str | int | bool | Tuple[str, ...]] | None = None,
        comments: Iterable[str] = tuple(),
        build_file_name: str = "BUILD",
    ):
        owned_sources = (
            (kwargs or {}).get("sources") or default_sources_for_target_type(target_type) or tuple()
        )
        return cls(
            path,
            name,
            target_type.alias,
            triggering_sources,
            owned_sources,  # type: ignore[arg-type]
            kwargs=kwargs,
            comments=comments,
            build_file_name=build_file_name,
        )

    def __init__(
        self,
        path: str,
        name: str,
        type_alias: str,
        triggering_sources: Iterable[str],
        owned_sources: Iterable[str],
        *,
        kwargs: Mapping[str, str | int | bool | Tuple[str, ...]] | None = None,
        comments: Iterable[str] = tuple(),
        build_file_name: str = "BUILD",
    ) -> None:
        self.path = path
        self.name = name
        self.type_alias = type_alias
        self.triggering_sources = tuple(triggering_sources)
        self.owned_sources = tuple(owned_sources)
        self.kwargs = FrozenDict(kwargs or {})
        self.comments = tuple(comments)
        self.build_file_name = build_file_name

    @property
    def build_file_path(self) -> str:
        return os.path.join(self.path, self.build_file_name)

    @property
    def address(self) -> Address:
        return Address(self.path, target_name=self.name)

    def rename(self, new_name: str) -> PutativeTarget:
        """A copy of this object with the name replaced to the given name."""
        # We assume that a rename imposes an explicit "name=" kwarg, overriding any previous
        # explicit "name=" kwarg, even if the rename happens to be to the default name.
        return dataclasses.replace(self, name=new_name, kwargs={**self.kwargs, "name": new_name})

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
                val_str = ",".join(val_parts)
                return f"[{val_str},\n{indent}]"
            return repr(v)

        if self.kwargs:
            kwargs_str_parts = [f"\n{indent}{k}={fmt_val(v)}" for k, v in self.kwargs.items()]
            kwargs_str = ",".join(kwargs_str_parts) + ",\n"
        else:
            kwargs_str = ""

        comment_str = ("\n".join(self.comments) + "\n") if self.comments else ""
        return f"{comment_str}{self.type_alias}({kwargs_str})\n"


class PutativeTargets(DeduplicatedCollection[PutativeTarget]):
    sort_input = True

    @classmethod
    def merge(cls, tgts_iters: Iterable[PutativeTargets]) -> PutativeTargets:
        all_tgts: List[PutativeTarget] = []
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
            "--build-file-indent",
            advanced=True,
            type=str,
            default="    ",
            help="The indent to use when auto-editing BUILD files.",
        )

    @property
    def build_file_indent(self) -> str:
        return cast(str, self.options.build_file_indent)


class Tailor(Goal):
    subsystem_cls = TailorSubsystem


def group_by_dir(paths: Iterable[str]) -> dict[str, set[str]]:
    """For a list of file paths, returns a dict of directory path -> files in that dir."""
    ret = defaultdict(set)
    for path in paths:
        dirname, filename = os.path.split(path)
        ret[dirname].add(filename)
    return ret


def group_by_build_file(ptgts: Iterable[PutativeTarget]) -> Dict[str, List[PutativeTarget]]:
    ret = defaultdict(list)
    for ptgt in ptgts:
        ret[ptgt.build_file_path].append(ptgt)
    return ret


class AllOwnedSources(DeduplicatedCollection[str]):
    """All files in the project already owned by targets."""


@rule(desc="Determine all files already owned by targets", level=LogLevel.DEBUG)
async def determine_all_owned_sources() -> AllOwnedSources:
    all_tgts = await Get(UnexpandedTargets, AddressSpecs([MaybeEmptyDescendantAddresses("")]))
    all_sources_paths = await MultiGet(
        Get(SourcesPaths, SourcesPathsRequest(tgt.get(Sources))) for tgt in all_tgts
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
    existing_addrs: Set[str] = {tgt.address.spec for tgt in all_existing_tgts}
    uniquely_named_putative_targets: List[PutativeTarget] = []
    for ptgt in ptgts:
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
        PathGlobs(Sources.prefix_glob_with_dirpath(ptgt.path, glob) for glob in ptgt.owned_sources),
    )
    source_path_set = set(source_paths.files)
    source_dirs = {os.path.dirname(path) for path in source_path_set}
    possible_owners = await Get(
        UnexpandedTargets, AddressSpecs(AscendantAddresses(d) for d in source_dirs)
    )
    possible_owners_sources = await MultiGet(
        Get(SourcesPaths, SourcesPathsRequest(t.get(Sources))) for t in possible_owners
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
    indent: str


@dataclass(frozen=True)
class EditedBuildFiles:
    digest: Digest
    created_paths: Tuple[str, ...]
    updated_paths: Tuple[str, ...]


def make_content_str(
    existing_content: str | None, indent: str, pts: Iterable[PutativeTarget]
) -> str:
    new_content = ([] if existing_content is None else [existing_content]) + [
        pt.generate_build_file_stanza(indent) for pt in pts
    ]
    new_content = [s.rstrip() for s in new_content]
    return "\n\n".join(new_content) + "\n"


@rule(desc="Edit BUILD files with new targets", level=LogLevel.DEBUG)
async def edit_build_files(req: EditBuildFilesRequest) -> EditedBuildFiles:
    ptgts_by_build_file = group_by_build_file(req.putative_targets)
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
            None if existing_content_bytes is None else existing_content_bytes.decode()
        )
        new_content_bytes = make_content_str(existing_content, req.indent, pts).encode()
        return FileContent(bf_path, new_content_bytes)

    new_digest = await Get(
        Digest,
        CreateDigest([make_content(path, ptgts) for path, ptgts in ptgts_by_build_file.items()]),
    )

    updated = set(existing_build_files_contents_by_path.keys())
    created = set(ptgts_by_build_file.keys()) - updated
    return EditedBuildFiles(new_digest, tuple(sorted(created)), tuple(sorted(updated)))


@goal_rule
async def tailor(
    tailor_subsystem: TailorSubsystem,
    console: Console,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Tailor:
    putative_target_request_types = union_membership[PutativeTargetsRequest]
    putative_targets_results = await MultiGet(
        Get(PutativeTargets, PutativeTargetsRequest, req_type())
        for req_type in putative_target_request_types
    )
    putative_targets = PutativeTargets.merge(putative_targets_results)
    fixed_names_ptgts = await Get(UniquelyNamedPutativeTargets, PutativeTargets, putative_targets)
    fixed_sources_ptgts = await MultiGet(
        Get(DisjointSourcePutativeTarget, PutativeTarget, ptgt)
        for ptgt in fixed_names_ptgts.putative_targets
    )
    ptgts = [dspt.putative_target for dspt in fixed_sources_ptgts]

    if ptgts:
        edited_build_files = await Get(
            EditedBuildFiles,
            EditBuildFilesRequest(PutativeTargets(ptgts), tailor_subsystem.build_file_indent),
        )
        updated_build_files = set(edited_build_files.updated_paths)
        workspace.write_digest(edited_build_files.digest)
        ptgts_by_build_file = group_by_build_file(ptgts)
        for build_file_path, ptgts in ptgts_by_build_file.items():
            verb = "Updated" if build_file_path in updated_build_files else "Created"
            console.print_stdout(f"{verb} {console.blue(build_file_path)}:")
            for ptgt in ptgts:
                console.print_stdout(
                    f"  - Added {console.green(ptgt.type_alias)} target "
                    f"{console.cyan(ptgt.address.spec)}"
                )
    return Tailor(0)


def rules():
    return collect_rules()
