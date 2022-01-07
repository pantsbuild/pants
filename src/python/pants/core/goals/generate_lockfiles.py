# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Iterable, Sequence

from pants.engine.fs import Digest
from pants.engine.unions import union


@dataclass(frozen=True)
class Lockfile:
    """The result of generating a lockfile for a particular resolve."""

    digest: Digest
    resolve_name: str
    path: str


@union
@dataclass(frozen=True)
class LockfileRequest:
    """A union base for generating ecosystem-specific lockfiles.

    Each language ecosystem should set up a subclass of `LockfileRequest`, like
    `PythonLockfileRequest` and `CoursierLockfileRequest`, and register a union rule. They should
    also set up a simple rule that goes from that class -> `WrappedLockfileRequest`.

    Subclasses will usually want to add additional properties, such as Python interpreter
    constraints.
    """

    resolve_name: str
    lockfile_dest: str


@dataclass(frozen=True)
class WrappedLockfileRequest:
    request: LockfileRequest


@union
class ToolLockfileSentinel:
    """Tools use this as an entry point to say how to generate their tool lockfile.

    Each language ecosystem should set up a union member of `LockfileRequest`, like
    `PythonLockfileRequest`, as explained in that class's docstring.

    Then, each tool should subclass `ToolLockfileSentinel` and set up a rule that goes from the
    subclass -> the language's lockfile request, e.g. BlackLockfileSentinel ->
    PythonLockfileRequest. Register a union rule for the `ToolLockfileSentinel` subclass.
    """

    options_scope: ClassVar[str]


DEFAULT_TOOL_LOCKFILE = "<default>"
NO_TOOL_LOCKFILE = "<none>"


class UnrecognizedResolveNamesError(Exception):
    def __init__(
        self,
        unrecognized_resolve_names: list[str],
        all_valid_names: Iterable[str],
        *,
        description_of_origin: str,
    ) -> None:
        # TODO(#12314): maybe implement "Did you mean?"
        if len(unrecognized_resolve_names) == 1:
            unrecognized_str = unrecognized_resolve_names[0]
            name_description = "name"
        else:
            unrecognized_str = str(sorted(unrecognized_resolve_names))
            name_description = "names"
        super().__init__(
            f"Unrecognized resolve {name_description} from {description_of_origin}: "
            f"{unrecognized_str}\n\nAll valid resolve names: {sorted(all_valid_names)}"
        )


class AmbiguousResolveNamesError(Exception):
    def __init__(self, ambiguous_names: list[str]) -> None:
        if len(ambiguous_names) == 1:
            first_paragraph = (
                "A resolve name from the option `[python].experimental_resolves` collides with the "
                f"name of a tool resolve: {ambiguous_names[0]}"
            )
        else:
            first_paragraph = (
                "Some resolve names from the option `[python].experimental_resolves` collide with "
                f"the names of tool resolves: {sorted(ambiguous_names)}"
            )
        super().__init__(
            f"{first_paragraph}\n\n"
            "To fix, please update `[python].experimental_resolves` to use different resolve names."
        )


def determine_resolves_to_generate(
    all_user_resolves: Iterable[str],
    all_tool_sentinels: Iterable[type[ToolLockfileSentinel]],
    requested_resolve_names: Sequence[str],
) -> tuple[list[str], list[type[ToolLockfileSentinel]]]:
    """Apply the `--resolve` option to determine which resolves are specified.

    Return a tuple of `(user_resolves, tool_lockfile_sentinels)`.
    """
    resolve_names_to_sentinels = {
        sentinel.options_scope: sentinel for sentinel in all_tool_sentinels
    }

    ambiguous_resolve_names = [
        resolve_name
        for resolve_name in all_user_resolves
        if resolve_name in resolve_names_to_sentinels
    ]
    if ambiguous_resolve_names:
        raise AmbiguousResolveNamesError(ambiguous_resolve_names)

    if not requested_resolve_names:
        return list(all_user_resolves), list(all_tool_sentinels)

    specified_user_resolves = []
    specified_sentinels = []
    unrecognized_resolve_names = []
    for resolve_name in requested_resolve_names:
        sentinel = resolve_names_to_sentinels.get(resolve_name)
        if sentinel:
            specified_sentinels.append(sentinel)
        elif resolve_name in all_user_resolves:
            specified_user_resolves.append(resolve_name)
        else:
            unrecognized_resolve_names.append(resolve_name)

    if unrecognized_resolve_names:
        raise UnrecognizedResolveNamesError(
            unrecognized_resolve_names,
            {*all_user_resolves, *resolve_names_to_sentinels.keys()},
            description_of_origin="the option `--generate-lockfiles-resolve`",
        )

    return specified_user_resolves, specified_sentinels


def filter_tool_lockfile_requests(
    specified_requests: Sequence[WrappedLockfileRequest], *, resolve_specified: bool
) -> list[LockfileRequest]:
    result = []
    for wrapped_req in specified_requests:
        req = wrapped_req.request
        if req.lockfile_dest not in (NO_TOOL_LOCKFILE, DEFAULT_TOOL_LOCKFILE):
            result.append(req)
            continue
        if resolve_specified:
            resolve = req.resolve_name
            raise ValueError(
                f"You requested to generate a lockfile for {resolve} because "
                "you included it in `--generate-lockfiles-resolve`, but "
                f"`[{resolve}].lockfile` is set to `{req.lockfile_dest}` "
                "so a lockfile will not be generated.\n\n"
                f"If you would like to generate a lockfile for {resolve}, please "
                f"set `[{resolve}].lockfile` to the path where it should be "
                "generated and run again."
            )

    return result
