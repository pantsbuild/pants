# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
import os
from abc import ABCMeta
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Tuple, Union

from pants.base.specs import AddressSpecs, DescendantAddresses
from pants.engine.collection import DeduplicatedCollection
from pants.engine.console import Console
from pants.engine.fs import CreateDigest, Digest, DigestContents, FileContent, PathGlobs, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule, rule
from pants.engine.target import Targets
from pants.engine.unions import UnionMembership, union
from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@union
class PutativeTargetsRequest(metaclass=ABCMeta):
    pass


@frozen_after_init
@dataclass(order=True, unsafe_hash=True)
class PutativeTarget:
    """A potential target to add, detected by various heuristics."""

    # Note that field order is such that the dataclass order will be by address (path+name).
    path: str
    name: str
    type_alias: str
    # The sources that triggered creating of this putative target.
    sources: Tuple[str, ...]
    # Note that we generate the BUILD file target entry exclusively from these kwargs (plus the
    # type_alias), not from the name and sources fields above, which are broken out for other uses.
    # This allows the creator of instances of this class to control whether the generated
    # target should assume default kwarg values or provide them explicitly.
    kwargs: FrozenDict[str, Union[str, int, bool, Tuple[str, ...]]]
    build_file_name: str

    def __init__(
        self,
        path: str,
        name: str,
        type_alias: str,
        sources: Iterable[str],
        *,
        kwargs: Union[None, Mapping[str, Union[str, int, bool, Tuple[str, ...]]]] = None,
        build_file_name="BUILD",
    ) -> None:
        self.path = path
        self.name = name
        self.type_alias = type_alias
        self.sources = tuple(sources)
        self.kwargs = FrozenDict(kwargs or {})
        self.build_file_name = build_file_name

    @property
    def build_file_path(self) -> str:
        return os.path.join(self.path, self.build_file_name)

    @property
    def address_spec(self) -> str:
        return f"{self.path}:{self.name}"

    def generate_build_file_stanza(self) -> str:
        indent = "  "

        if self.kwargs:
            kwargs_str_parts = [f"\n{indent}{k}={repr(v)}" for k, v in self.kwargs.items()]
            kwargs_str = ",".join(kwargs_str_parts) + ",\n"
        else:
            kwargs_str = ""
        return f"{self.type_alias}({kwargs_str})\n"


class PutativeTargets(DeduplicatedCollection[PutativeTarget]):
    sort_input = True

    @classmethod
    def merge(cls, tgts_iters: Iterable["PutativeTargets"]) -> "PutativeTargets":
        all_tgts: List[PutativeTarget] = []
        for tgts in tgts_iters:
            all_tgts.extend(tgts)
        return cls(all_tgts)


class InitSubsystem(LineOriented, GoalSubsystem):
    name = "init"
    help = "Generate config for working with Pants."


class Init(Goal):
    subsystem_cls = InitSubsystem


@dataclass(frozen=True)
class EditBuildFilesRequest:
    putative_targets: PutativeTargets


@dataclass(frozen=True)
class EditedBuildFiles:
    digest: Digest
    created_paths: Tuple[str, ...]
    updated_paths: Tuple[str, ...]


def group_by_build_file(ptgts: Iterable[PutativeTarget]) -> Dict[str, List[PutativeTarget]]:
    ret = defaultdict(list)
    for ptgt in ptgts:
        ret[ptgt.build_file_path].append(ptgt)
    return ret


@rule
async def edit_build_files(req: EditBuildFilesRequest) -> EditedBuildFiles:
    ptgts_by_build_file = group_by_build_file(req.putative_targets)
    existing_build_files_contents = await Get(DigestContents, PathGlobs(ptgts_by_build_file.keys()))
    existing_build_files_contents_by_path = {
        ebfc.path: ebfc.content for ebfc in existing_build_files_contents
    }

    def make_content(bf_path: str, pts: Iterable[PutativeTarget]) -> FileContent:
        existing_content = existing_build_files_contents_by_path.get(bf_path)
        new_content = ([] if existing_content is None else [existing_content.decode()]) + [
            pt.generate_build_file_stanza() for pt in pts
        ]
        new_content_bytes = "\n\n".join(new_content).encode()
        return FileContent(bf_path, new_content_bytes)

    new_digest = await Get(
        Digest,
        CreateDigest([make_content(path, ptgts) for path, ptgts in ptgts_by_build_file.items()]),
    )

    updated = set(existing_build_files_contents_by_path.keys())
    created = set(ptgts_by_build_file.keys()) - updated
    return EditedBuildFiles(new_digest, tuple(sorted(created)), tuple(sorted(updated)))


@goal_rule
async def init(
    init_subsystem: InitSubsystem,
    console: Console,
    workspace: Workspace,
    union_membership: UnionMembership,
) -> Init:
    putative_target_request_types = union_membership[PutativeTargetsRequest]
    putative_target_reqs = [req_type() for req_type in putative_target_request_types]
    putative_targets_results = await MultiGet(
        Get(PutativeTargets, PutativeTargetsRequest, req) for req in putative_target_reqs
    )
    all_putative_targets = PutativeTargets.merge(putative_targets_results)
    all_existing_tgts = await Get(Targets, AddressSpecs([DescendantAddresses("")]))
    addr_to_existing_tgt = {
        f"{tgt.address.spec_path}:{tgt.address.target_name}": tgt for tgt in all_existing_tgts
    }

    conflicting_ptgts: List[PutativeTarget] = []
    nonconflicting_ptgts: List[PutativeTarget] = []

    for ptgt in all_putative_targets:
        (
            conflicting_ptgts if ptgt.address_spec in addr_to_existing_tgt else nonconflicting_ptgts
        ).append(ptgt)

    conflicting_ptgts_by_build_file = group_by_build_file(conflicting_ptgts)
    nonconflicting_ptgts_by_build_file = group_by_build_file(nonconflicting_ptgts)

    # Edit BUILD files for the putative targets whose addresses don't conflict with
    # those of existing targets.
    edited_build_files = await Get(
        EditedBuildFiles,
        EditBuildFilesRequest(
            PutativeTargets(
                ptgt
                for ptgt in all_putative_targets
                if ptgt.address_spec not in addr_to_existing_tgt
            )
        ),
    )
    updated_build_files = set(edited_build_files.updated_paths)

    workspace.write_digest(edited_build_files.digest)

    with init_subsystem.line_oriented(console) as print_stdout:
        if nonconflicting_ptgts_by_build_file:
            print_stdout("")
            print_stdout(console.magenta("Automatic BUILD file edits"))
            print_stdout(console.magenta("--------------------------"))
            for build_file_path, ptgts in nonconflicting_ptgts_by_build_file.items():
                verb = "Updated" if build_file_path in updated_build_files else "Created"
                print_stdout(f"{verb} {console.blue(build_file_path)}:")
                for ptgt in ptgts:
                    print_stdout(
                        f"  - Added {console.green(ptgt.type_alias)} target "
                        f"{console.cyan(ptgt.address_spec)}"
                    )
        if conflicting_ptgts_by_build_file:
            print_stdout("")
            print_stdout(console.magenta("Suggested manual BUILD file edits"))
            print_stdout(console.magenta("---------------------------------"))
            for build_file_path, ptgts in conflicting_ptgts_by_build_file.items():
                print_stdout(f"Edit {console.blue(build_file_path)}:")
                for ptgt in ptgts:
                    print_stdout(
                        f"  - Add a {console.green(ptgt.type_alias)} target for these "
                        f"sources: {', '.join(console.green(src) for src in ptgt.sources)}"
                    )

    return Init(0)


def rules():
    return collect_rules()
