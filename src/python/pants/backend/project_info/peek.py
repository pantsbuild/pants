# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import collections.abc
import json
import os
from dataclasses import asdict, is_dataclass
from enum import Enum
from typing import Any, Iterable, Mapping, cast

from pkg_resources import Requirement

from pants.engine.addresses import Address, BuildFileAddress
from pants.engine.console import Console
from pants.engine.fs import DigestContents, FileContent, PathGlobs
from pants.engine.goal import Goal, GoalSubsystem, Outputting
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import Target, UnexpandedTargets


class OutputOptions(Enum):
    RAW = "raw"
    JSON = "json"


class PeekSubsystem(Outputting, GoalSubsystem):
    """Display BUILD file info to the console.

    In its most basic form, `peek` just prints the contents of a BUILD file. It can also display
    multiple BUILD files, or render normalized target metadata as JSON for consumption by other
    programs.
    """

    name = "peek"
    help = "Display BUILD target info"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--output",
            type=OutputOptions,
            default=OutputOptions.JSON,
            help=(
                "Which output style peek should use: `json` will show each target as a seperate "
                "entry, whereas `raw` will simply show the original non-normalized BUILD files."
            ),
        )
        register(
            "--exclude-defaults",
            type=bool,
            default=False,
            help=(
                "Whether to leave off values that match the target-defined default values "
                "when using `json` output."
            ),
        )

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


def _render_raw(fcs: Iterable[FileContent]) -> str:
    sorted_fcs = sorted(fcs, key=lambda fc: fc.path)
    rendereds = map(_render_raw_build_file, sorted_fcs)
    return os.linesep.join(rendereds)


def _render_raw_build_file(fc: FileContent, encoding: str = "utf-8") -> str:
    dashes = "-" * len(fc.path)
    content = fc.content.decode(encoding)
    parts = [dashes, fc.path, dashes, content]
    if not content.endswith(os.linesep):
        parts.append("")
    return os.linesep.join(parts)


_nothing = object()


def _render_json(ts: Iterable[Target], exclude_defaults: bool = False) -> str:
    targets: Iterable[Mapping[str, Any]] = [
        {
            "address": t.address.spec,
            "target_type": t.alias,
            **{
                k.alias: v.value
                for k, v in t.field_values.items()
                if not (exclude_defaults and getattr(k, "default", _nothing) == v.value)
            },
        }
        for t in ts
    ]
    return f"{json.dumps(targets, indent=2, cls=_PeekJsonEncoder)}\n"


class _PeekJsonEncoder(json.JSONEncoder):
    """Allow us to serialize some commmonly-found types in BUILD files."""

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


@goal_rule
async def peek(
    console: Console,
    subsys: PeekSubsystem,
    targets: UnexpandedTargets,
) -> Peek:
    if subsys.output_type == OutputOptions.RAW:
        build_file_addresses = await MultiGet(
            Get(BuildFileAddress, Address, t.address) for t in targets
        )
        build_file_paths = {a.rel_path for a in build_file_addresses}
        digest_contents = await Get(DigestContents, PathGlobs(build_file_paths))
        output = _render_raw(digest_contents)
    elif subsys.output_type == OutputOptions.JSON:
        output = _render_json(targets, subsys.exclude_defaults)
    else:
        raise AssertionError(f"output_type not one of {tuple(OutputOptions)}")

    with subsys.output(console) as write_stdout:
        write_stdout(output)

    return Peek(exit_code=0)


def rules():
    return collect_rules()
