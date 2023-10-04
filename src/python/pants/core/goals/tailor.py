# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import itertools
import logging
import os
from abc import ABCMeta
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Mapping, cast

from pants.base.specs import AncestorGlobSpec, DirLiteralSpec, RawSpecs, Specs
from pants.build_graph.address import Address
from pants.engine.collection import DeduplicatedCollection
from pants.engine.console import Console
from pants.engine.environment import EnvironmentName
from pants.engine.fs import (
    CreateDigest,
    Digest,
    DigestContents,
    FileContent,
    PathGlobs,
    Paths,
    SpecsPaths,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.build_files import BuildFileOptions
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import (
    AllUnexpandedTargets,
    MultipleSourcesField,
    OptionalSingleSourceField,
    SourcesField,
    SourcesPaths,
    SourcesPathsRequest,
    Target,
    UnexpandedTargets,
)
from pants.engine.unions import UnionMembership, union
from pants.option.option_types import BoolOption, DictOption, StrListOption, StrOption
from pants.source.filespec import FilespecMatcher
from pants.util.docutil import bin_name, doc_url
from pants.util.frozendict import FrozenDict
from pants.util.logging import LogLevel
from pants.util.memo import memoized
from pants.util.strutil import help_text, softwrap

logger = logging.getLogger(__name__)


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class PutativeTargetsRequest(metaclass=ABCMeta):
    dirs: tuple[str, ...]

    def path_globs(self, *filename_globs: str) -> PathGlobs:
        return PathGlobs(os.path.join(d, glob) for d in self.dirs for glob in filename_globs)


@dataclass(frozen=True)
class PutativeTargetsSearchPaths:
    dirs: tuple[str, ...]

    def path_globs(self, filename_glob: str) -> PathGlobs:
        return PathGlobs(globs=(os.path.join(d, filename_glob) for d in self.dirs))


@memoized
def default_sources_for_target_type(tgt_type: type[Target]) -> tuple[str, ...]:
    for field in tgt_type.core_fields:
        if issubclass(field, OptionalSingleSourceField):
            return (field.default,) if field.default else tuple()
        if issubclass(field, MultipleSourcesField):
            return field.default or tuple()
    return tuple()


def has_source_or_sources_field(tgt_type: type[Target]) -> bool:
    """Tell whether a given target type has a `source` or `sources` field.

    This may be useful when determining whether it's possible to tailor a target with the passed
    source(s) field value if the target doesn't have such a field in the first place.
    """
    for field in tgt_type.core_fields:
        if issubclass(field, (OptionalSingleSourceField, MultipleSourcesField)):
            return True
    return False


@dataclass(order=True, frozen=True)
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
    # TODO: We can derive the default source globs for that type from BuildConfiguration.
    #  However that is fiddly and not a high priority.
    owned_sources: tuple[str, ...]

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

        kwargs = kwargs or {}
        explicit_sources = cast(
            "tuple[str, ...] | None",
            (kwargs["source"],) if "source" in kwargs else kwargs.get("sources"),
        )
        if explicit_sources is not None and not isinstance(explicit_sources, tuple):
            raise TypeError(
                softwrap(
                    f"""
                    `source` or `sources` passed to PutativeTarget.for_target_type(kwargs=)`, but
                    it was not the correct type. `source` must be `str` and `sources` must be
                    `tuple[str, ...]`. Was `{explicit_sources}` with type `{type(explicit_sources)}`.
                    """
                )
            )

        if (explicit_sources or triggering_sources) and not has_source_or_sources_field(
            target_type
        ):
            raise AssertionError(
                softwrap(
                    f"""
                    A target of type {target_type.__name__} was proposed at
                    address {path}:{name} with explicit sources {', '.join(explicit_sources or triggering_sources)},
                    but this target type does not have a `source` or `sources` field.
                    """
                )
            )
        default_sources = default_sources_for_target_type(target_type)
        owned_sources = explicit_sources or default_sources or tuple()
        return cls(
            path,
            name,
            target_type.alias,
            triggering_sources,
            owned_sources,
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
        kwargs: Mapping[str, str | int | bool | tuple[str, ...]] | None = None,
        comments: Iterable[str] = tuple(),
    ) -> None:
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "type_alias", type_alias)
        object.__setattr__(self, "triggering_sources", tuple(triggering_sources))
        object.__setattr__(self, "owned_sources", tuple(owned_sources))
        object.__setattr__(self, "kwargs", FrozenDict(kwargs or {}))
        object.__setattr__(self, "comments", tuple(comments))

    @property
    def address(self) -> Address:
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

        has_name = self.name != os.path.basename(self.path)
        if self.kwargs or has_name:
            _kwargs = {
                **({"name": self.name} if has_name else {}),
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
    help = help_text(
        """
        Auto-generate BUILD file targets for new source files.

        Each specific `tailor` implementation may be disabled through language-specific options,
        e.g. `[python].tailor_pex_binary_targets` and `[shell-setup].tailor`.
        """
    )

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return PutativeTargetsRequest in union_membership

    check = BoolOption(
        default=False,
        help=softwrap(
            """
            Do not write changes to disk, only write back what would change. Return code
            0 means there would be no changes, and 1 means that there would be.
            """
        ),
    )
    build_file_name = StrOption(
        default="BUILD",
        help=softwrap(
            """
            The name to use for generated BUILD files.

            This must be compatible with `[GLOBAL].build_patterns`.
            """
        ),
        advanced=True,
    )
    build_file_header = StrOption(
        default=None,
        help="A header, e.g., a copyright notice, to add to the content of created BUILD files.",
        advanced=True,
    )
    build_file_indent = StrOption(
        default="    ",
        help="The indent to use when auto-editing BUILD files.",
        advanced=True,
    )
    _alias_mapping = DictOption[str](
        help=softwrap(
            f"""
            A mapping from standard target type to custom type to use instead. The custom
            type can be a custom target type or a macro that offers compatible functionality
            to the one it replaces (see {doc_url('macros')}).
            """
        ),
        advanced=True,
    )
    ignore_paths = StrListOption(
        help=softwrap(
            """
            Do not edit or create BUILD files at these paths.

            Can use literal file names and/or globs, e.g. `['project/BUILD, 'ignore_me/**']`.

            This augments the option `[GLOBAL].build_ignore`, which tells Pants to also not
            _read_ BUILD files at certain paths. In contrast, this option only tells Pants to
            not edit/create BUILD files at the specified paths.
            """
        ),
        advanced=True,
    )
    _ignore_adding_targets = StrListOption(
        help=softwrap(
            """
            Do not add these target definitions.

            Expects a list of target addresses that would normally be added by `tailor`,
            e.g. `['project:tgt']`. To find these names, you can run `tailor --check`, then
            combine the BUILD file path with the target's name. For example, if `tailor`
            would add the target `bin` to `project/BUILD`, then the address would be
            `project:bin`. If the BUILD file is at the root of your repository, use `//` for
            the path, e.g. `//:bin`.

            Does not work with macros.
            """
        ),
        advanced=True,
    )

    @property
    def ignore_adding_targets(self) -> set[str]:
        return set(self._ignore_adding_targets)

    def alias_for(self, standard_type: str) -> str | None:
        # The get() could return None, but casting to str | None errors.
        # This cast suffices to avoid typecheck errors.
        return cast(str, self._alias_mapping.get(standard_type))

    def validate_build_file_name(self, build_file_patterns: tuple[str, ...]) -> None:
        """Check that the specified BUILD file name works with the repository's BUILD file
        patterns."""
        filespec_matcher = FilespecMatcher(build_file_patterns, ())
        if not bool(filespec_matcher.matches([self.build_file_name])):
            raise ValueError(
                softwrap(
                    f"""
                The option `[{self.options_scope}].build_file_name` is set to
                `{self.build_file_name}`, which is not compatible with
                `[GLOBAL].build_patterns`: {sorted(build_file_patterns)}. This means that
                generated BUILD files would be ignored.\n\n
                To fix, please update the options so that they are compatible.
                """
                )
            )

    def filter_by_ignores(
        self, putative_targets: Iterable[PutativeTarget], build_file_ignores: tuple[str, ...]
    ) -> Iterator[PutativeTarget]:
        ignore_paths_filespec_matcher = FilespecMatcher(
            (*self.ignore_paths, *build_file_ignores), ()
        )
        for ptgt in putative_targets:
            is_ignored_file = bool(
                ignore_paths_filespec_matcher.matches(
                    [os.path.join(ptgt.path, self.build_file_name)]
                ),
            )
            if is_ignored_file:
                continue
            # Note that `tailor` can only generate explicit targets, so we don't need to
            # worry about generated address syntax (`#`) or file address syntax.
            address = f"{ptgt.path or '//'}:{ptgt.name}"
            if address in self.ignore_adding_targets:
                continue
            yield ptgt


class TailorGoal(Goal):
    subsystem_cls = TailorSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


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
async def determine_all_owned_sources(all_tgts: AllUnexpandedTargets) -> AllOwnedSources:
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
async def rename_conflicting_targets(
    ptgts: PutativeTargets, all_existing_tgts: AllUnexpandedTargets
) -> UniquelyNamedPutativeTargets:
    """Ensure that no target addresses collide."""
    existing_addrs: set[str] = {tgt.address.spec for tgt in all_existing_tgts}
    uniquely_named_putative_targets: list[PutativeTarget] = []
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
        PathGlobs(
            SourcesField.prefix_glob_with_dirpath(ptgt.path, glob) for glob in ptgt.owned_sources
        ),
    )
    source_path_set = set(source_paths.files)
    source_dirs = {os.path.dirname(path) for path in source_path_set}
    possible_owners = await Get(
        UnexpandedTargets,
        RawSpecs(
            ancestor_globs=tuple(AncestorGlobSpec(d) for d in source_dirs),
            description_of_origin="the `tailor` goal",
        ),
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


def spec_with_build_to_dir(spec: RawSpecs, build_file_patterns: tuple[str, ...]) -> RawSpecs:
    """Convert a spec like `path/to/BUILD` into `path/to`, which is probably the intention."""

    filespec_matcher = FilespecMatcher(build_file_patterns, ())

    def is_build_file(s: str):
        return bool(filespec_matcher.matches([s]))

    new_file_literals = []
    new_dir_literals = []

    # handles existing BUILD files
    for file_literal in spec.file_literals:
        path = Path(file_literal.file)
        if is_build_file(path.name):
            # convert FileLiteralSpec into DirLiteralSpec
            new_dir_literals.append(DirLiteralSpec(path.parent.as_posix()))
        else:
            new_file_literals.append(file_literal)

    # If the BUILD file doesn't exist (possibly because it was deleted)
    # it will appear as a dir_literal
    for dir_literal in spec.dir_literals:
        path = Path(dir_literal.directory)
        if is_build_file(path.name):
            new_dir_literals.append(DirLiteralSpec(path.parent.as_posix()))
        else:
            new_dir_literals.append(dir_literal)

    return dataclasses.replace(
        spec, dir_literals=tuple(new_dir_literals), file_literals=tuple(new_file_literals)
    )


def resolve_specs_with_build(specs: Specs, build_file_patterns: tuple[str, ...]) -> Specs:
    """Convert Specs with specs like `path/to/BUILD` into `path/to`, which is probably the
    intention."""
    new_includes = spec_with_build_to_dir(specs.includes, build_file_patterns)
    new_ignores = spec_with_build_to_dir(specs.ignores, build_file_patterns)
    return dataclasses.replace(specs, includes=new_includes, ignores=new_ignores)


@goal_rule
async def tailor(
    tailor_subsystem: TailorSubsystem,
    console: Console,
    workspace: Workspace,
    union_membership: UnionMembership,
    specs: Specs,
    build_file_options: BuildFileOptions,
) -> TailorGoal:
    tailor_subsystem.validate_build_file_name(build_file_options.patterns)

    specs = resolve_specs_with_build(specs, build_file_options.patterns)

    if not specs:
        if not specs.includes.from_change_detection:
            logger.warning(
                softwrap(
                    f"""\
                    No arguments specified with `{bin_name()} tailor`, so the goal will do nothing.

                    Instead, you should provide arguments like this:

                      * `{bin_name()} tailor ::` to run on everything
                      * `{bin_name()} tailor dir::` to run on `dir` and subdirs
                      * `{bin_name()} tailor dir` to run on `dir`
                      * `{bin_name()} tailor dir/{tailor_subsystem.build_file_name}` to run on `dir`
                      * `{bin_name()} --changed-since=HEAD tailor` to only run on changed and new files
                    """
                )
            )
        return TailorGoal(exit_code=0)

    specs_paths = await Get(SpecsPaths, Specs, specs)
    dir_search_paths = tuple(sorted({os.path.dirname(f) for f in specs_paths.files}))

    putative_targets_results = await MultiGet(
        Get(PutativeTargets, PutativeTargetsRequest, req_type(dir_search_paths))
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
            f"  - Add {console.green(ptgt.type_alias)} target {console.cyan(ptgt.name)}"
            for ptgt in ptgts
        )
        if build_file_path in updated_build_files:
            verb = "Would update" if tailor_subsystem.check else "Updated"
        else:
            verb = "Would create" if tailor_subsystem.check else "Created"
        console.print_stdout(f"{verb} {console.blue(build_file_path)}:\n{formatted_changes}")

    if tailor_subsystem.check:
        console.print_stdout(f"\nTo fix `tailor` failures, run `{bin_name()} tailor`.")

    return TailorGoal(exit_code=1 if tailor_subsystem.check else 0)


def rules():
    return collect_rules()
