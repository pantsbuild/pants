# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import collections
import json
import os
from dataclasses import asdict, dataclass, is_dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, cast

from pkg_resources import Requirement

from pants.engine.addresses import Address, BuildFileAddress
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.fs import DigestContents, FileContent, PathGlobs
from pants.engine.goal import Goal, GoalSubsystem, Outputting
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    HydratedSources,
    HydrateSourcesRequest,
    Sources,
    Target,
    Targets,
    UnexpandedTargets,
)


# TODO: Delete this in 2.9.0.dev0.
class OutputOptions(Enum):
    RAW = "raw"
    JSON = "json"


class PeekSubsystem(Outputting, GoalSubsystem):
    """Display detailed target information in JSON form."""

    name = "peek"
    help = "Display BUILD target info"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--output",
            type=OutputOptions,
            default=OutputOptions.JSON,
            removal_version="2.9.0.dev0",
            removal_hint="Output will always be JSON. If you need the raw BUILD file contents, "
            "look at it directly!",
            help=(
                "Which output style peek should use: `json` will show each target as a seperate "
                "entry, whereas `raw` will simply show the original non-normalized BUILD files."
            ),
        )
        register(
            "--exclude-defaults",
            type=bool,
            default=False,
            help="Whether to leave off values that match the target-defined default values.",
        )

    # TODO: Delete this in 2.9.0.dev0.
    @property
    def output_type(self) -> OutputOptions:
        """Get the output type from options.

        Must be renamed here because `output` conflicts with `Outputting` class.
        """
        return cast(OutputOptions, self.options.output)

    @property
    def exclude_defaults(self) -> bool:
        return cast(bool, self.options.exclude_defaults)


class Peek(Goal):
    subsystem_cls = PeekSubsystem


# TODO: Delete this in 2.9.0.dev0.
def _render_raw(fcs: Iterable[FileContent]) -> str:
    sorted_fcs = sorted(fcs, key=lambda fc: fc.path)
    rendereds = map(_render_raw_build_file, sorted_fcs)
    return os.linesep.join(rendereds)


# TODO: Delete this in 2.9.0.dev0.
def _render_raw_build_file(fc: FileContent, encoding: str = "utf-8") -> str:
    dashes = "-" * len(fc.path)
    content = fc.content.decode(encoding)
    parts = [dashes, fc.path, dashes, content]
    if not content.endswith(os.linesep):
        parts.append("")
    return os.linesep.join(parts)


@dataclass(frozen=True)
class TargetData:
    target: Target
    expanded_sources: tuple[str, ...] | None  # Target may not be of a type that has sources.
    expanded_dependencies: tuple[str, ...]


# I know, I know, data is already plural. Except in idiomatic use it isn't, so...
class TargetDatas(Collection[TargetData]):
    pass


def _render_json(tds: Iterable[TargetData], exclude_defaults: bool = False) -> str:
    nothing = object()

    targets: Iterable[Mapping[str, Any]] = [
        {
            "address": td.target.address.spec,
            "target_type": td.target.alias,
            **{
                k.alias: v.value
                for k, v in td.target.field_values.items()
                if not (exclude_defaults and getattr(k, "default", nothing) == v.value)
            },
            **({} if td.expanded_sources is None else {"expanded_sources": td.expanded_sources}),
            "expanded_dependencies": td.expanded_dependencies,
        }
        for td in tds
    ]
    return f"{json.dumps(targets, indent=2, cls=_PeekJsonEncoder)}\n"


class _PeekJsonEncoder(json.JSONEncoder):
    """Allow us to serialize some commmonlyfound types in BUILD files."""

    safe_to_str_types = (Requirement,)

    def default(self, o):
        """Return a serializable object for o."""
        if is_dataclass(o):
            return asdict(o)
        if isinstance(o, collections.abc.Mapping):
            return dict(o)
        if isinstance(o, collections.abc.Sequence):
            return list(o)
        try:
            return super().default(o)
        except TypeError:
            return str(o)


@rule
async def get_target_data(targets: UnexpandedTargets) -> TargetDatas:
    sorted_targets = sorted(targets, key=lambda tgt: tgt.address)

    dependencies_per_target = await MultiGet(
        Get(
            Targets,
            DependenciesRequest(tgt.get(Dependencies), include_special_cased_deps=True),
        )
        for tgt in sorted_targets
    )

    # Not all targets have a sources field, so we have to do a dance here.
    targets_with_sources = [tgt for tgt in sorted_targets if tgt.has_field(Sources)]
    all_hydrated_sources = await MultiGet(
        Get(HydratedSources, HydrateSourcesRequest(tgt[Sources])) for tgt in targets_with_sources
    )
    hydrated_sources_map = {
        tgt.address: hs for tgt, hs in zip(targets_with_sources, all_hydrated_sources)
    }
    sources_per_target = [hydrated_sources_map.get(tgt.address) for tgt in sorted_targets]

    return TargetDatas(
        TargetData(
            tgt, srcs.snapshot.files if srcs else None, tuple(dep.address.spec for dep in deps)
        )
        for tgt, srcs, deps in zip(sorted_targets, sources_per_target, dependencies_per_target)
    )


@goal_rule
async def peek(
    console: Console,
    subsys: PeekSubsystem,
    targets: UnexpandedTargets,
) -> Peek:
    # TODO: Delete this entire conditional in 2.9.0.dev0.
    if subsys.output_type == OutputOptions.RAW:
        build_file_addresses = await MultiGet(
            Get(BuildFileAddress, Address, t.address) for t in targets
        )
        build_file_paths = {a.rel_path for a in build_file_addresses}
        digest_contents = await Get(DigestContents, PathGlobs(build_file_paths))
        with subsys.output(console) as write_stdout:
            write_stdout(_render_raw(digest_contents))
        return Peek(exit_code=0)

    tds = await Get(TargetDatas, UnexpandedTargets, targets)
    output = _render_json(tds, subsys.exclude_defaults)
    with subsys.output(console) as write_stdout:
        write_stdout(output)
    return Peek(exit_code=0)


def rules():
    return collect_rules()
