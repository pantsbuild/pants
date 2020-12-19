# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import os
from dataclasses import asdict, is_dataclass
from enum import Enum
from itertools import repeat
from typing import Iterable, Tuple, TypeVar, Union, cast

from pkg_resources import Requirement

from pants.engine.addresses import Address, Addresses, BuildFileAddress
from pants.engine.console import Console
from pants.engine.fs import DigestContents, FileContent, PathGlobs
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import Target, Targets


class OutputOptions(Enum):
    RAW = "raw"
    JSON = "json"


class PeekSubsystem(GoalSubsystem):
    """Display BUILD file info to the console.

    In its most basic form, `peek` just prints the contents of a BUILD file. It can also display
    multiple BUILD files, or render normalized target metadata as JSON for consumption by other
    programs.
    """

    name = "peek"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--output",
            type=OutputOptions,
            default=OutputOptions.RAW,
            help="which output style peek should use",
        )

    @property
    def output(self) -> OutputOptions:
        return cast(OutputOptions, self.options.output)


class Peek(Goal):
    subsystem_cls = PeekSubsystem


_T = TypeVar("_T")
_U = TypeVar("_U")


def _intersperse(x: _T, ys: Iterable[_U]) -> Iterable[Union[_T, _U]]:
    # Use stateful iterator to safely iterate through first item
    it = iter(ys)
    for y in it:
        yield y
        break
    for x, y in zip(repeat(x), it):
        yield x
        yield y


def _render_raw(fc: FileContent, encoding: str = "utf-8") -> str:
    dashes = "-" * len(fc.path)
    content = fc.content.decode(encoding)
    parts = [dashes, fc.path, dashes, content]
    if not content.endswith(os.linesep):
        parts.append("")
    return os.linesep.join(parts)


def _render_json(ts: Iterable[Target]) -> str:
    data = dict(map(_target_to_kv, ts))
    return json.dumps(data, indent=2, cls=_PeekJsonEncoder)


def _target_to_kv(t: Target) -> Tuple[str, dict]:
    d = {k.alias: _prepare_value(v.value) for k, v in t.field_values.items()}
    d["alias"] = t.alias
    return t.address.spec, d


def _prepare_value(x: object) -> object:
    """Prepare the value to be JSON-serialized.

    If we can make it a dict, try that.  If not, str() it.
    """
    if is_dataclass(x):
        return asdict(x)
    else:
        return x


class _PeekJsonEncoder(json.JSONEncoder):
    """Allow us to serialize some commmonly-found types in BUILD files."""

    def default(self, o):
        """Return a serializable object for o."""
        if isinstance(o, Requirement):
            return str(o)
        else:
            return super().default(o)


@goal_rule
async def peek(
    console: Console,
    subsys: PeekSubsystem,
    addresses: Addresses,
) -> Peek:
    # TODO: better options for target selection (globs, transitive, etc)?
    targets: Iterable[Target]
    # TODO: handle target not found exceptions better here
    targets = await Get(Targets, Addresses, addresses)

    if subsys.output == OutputOptions.RAW:
        build_file_addresses = await MultiGet(
            Get(BuildFileAddress, Address, t.address) for t in targets
        )
        build_file_paths = {a.rel_path for a in build_file_addresses}
        digest_contents = await Get(DigestContents, PathGlobs(build_file_paths))
        # TODO: programmatically determine correct encoding
        rendereds = map(_render_raw, digest_contents)
        for output in _intersperse(os.linesep, rendereds):
            console.print_stdout(output)
    elif subsys.output == OutputOptions.JSON:
        console.print_stdout(_render_json(targets))

    return Peek(exit_code=0)


def rules():
    return collect_rules()
