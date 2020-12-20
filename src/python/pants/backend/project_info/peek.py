# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import collections.abc
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
from pants.engine.target import Target, UnexpandedTargets


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
            default=OutputOptions.JSON,
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


_nothing = object()


def _target_to_kv(t: Target, _nothing: object = _nothing) -> Tuple[str, dict]:
    d = {
        k.alias: v.value
        for k, v in t.field_values.items()
        # don't report default values in normalized output
        if getattr(k, "default", _nothing) != v.value
    }
    d.update(address=t.address.spec, target_type=t.alias)
    return t.address.spec, d


class _PeekJsonEncoder(json.JSONEncoder):
    """Allow us to serialize some commmonly-found types in BUILD files."""

    safe_to_str_types = (Requirement,)

    def default(self, o):
        """Return a serializable object for o."""
        if is_dataclass(o):
            return asdict(o)
        elif isinstance(o, collections.abc.Mapping):
            return dict(o)
        elif isinstance(o, collections.abc.Sequence):
            return list(o)
        elif isinstance(o, self.safe_to_str_types):
            return str(o)
        else:
            try:
                return super().default(o)
            except TypeError:
                # punt and just try str()
                # TODO: can we find a better strategy here?
                return str(o)


@goal_rule
async def peek(
    console: Console,
    subsys: PeekSubsystem,
    addresses: Addresses,
) -> Peek:
    # TODO: better options for target selection (globs, transitive, etc)?
    targets: Iterable[Target]
    # TODO: handle target not found exceptions better here
    targets = await Get(UnexpandedTargets, Addresses, addresses)

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
