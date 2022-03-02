# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Iterable, Sequence

from pants.engine.collection import Collection
from pants.engine.fs import Digest, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.unions import UnionMembership, union
from pants.option.option_types import StrListOption, StrOption
from pants.util.docutil import bin_name

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerateLockfileResult:
    """The result of generating a lockfile for a particular resolve."""

    digest: Digest
    resolve_name: str
    path: str


@union
@dataclass(frozen=True)
class GenerateLockfile:
    """A union base for generating ecosystem-specific lockfiles.

    Each language ecosystem should set up a subclass of `GenerateLockfile`, like
    `GeneratePythonLockfile` and `GenerateJVMLockfile`, and register a union rule. They should
    also set up a simple rule that goes from that class -> `WrappedGenerateLockfile`.

    Subclasses will usually want to add additional properties, such as what requirements to
    install and Python interpreter constraints.
    """

    resolve_name: str
    lockfile_dest: str


@dataclass(frozen=True)
class WrappedGenerateLockfile:
    request: GenerateLockfile


@union
class GenerateToolLockfileSentinel:
    """Tools use this as an entry point to say how to generate their tool lockfile.

    Each language ecosystem should set up a union member of `GenerateLockfile`, like
    `GeneratePythonLockfile`, as explained in that class's docstring.

    Then, each tool should subclass `GenerateToolLockfileSentinel` and set up a rule that goes from the
    subclass -> the language's lockfile request, e.g. BlackLockfileSentinel ->
    GeneratePythonLockfile. Register a union rule for the `GenerateToolLockfileSentinel` subclass.
    """

    resolve_name: ClassVar[str]


class UserGenerateLockfiles(Collection[GenerateLockfile]):
    """All user resolves for a particular language ecosystem to build.

    Each language ecosystem should set up a subclass of `RequestedUserResolveNames` (see its
    docstring), and implement a rule going from that subclass -> UserGenerateLockfiles. Each element
    in the returned `UserGenerateLockfiles` should be a subclass of `GenerateLockfile`, like
    `GeneratePythonLockfile`.
    """


@union
class KnownUserResolveNamesRequest:
    """A hook for a language ecosystem to declare which resolves it has defined.

    Each language ecosystem should set up a subclass and register it with a UnionRule. Implement a
    rule that goes from the subclass -> KnownUserResolveNames, usually by simply reading the
    `resolves` option from the relevant subsystem.
    """


@dataclass(frozen=True)
class KnownUserResolveNames:
    """All defined user resolves for a particular language ecosystem.

    See KnownUserResolveNamesRequest for how to use this type. `option_name` should be formatted
    like `[options-scope].resolves`
    """

    names: tuple[str, ...]
    option_name: str
    requested_resolve_names_cls: type[RequestedUserResolveNames]


@union
class RequestedUserResolveNames(Collection[str]):
    """The user resolves requested for a particular language ecosystem.

    Each language ecosystem should set up a subclass and register it with a UnionRule. Implement a
    rule that goes from the subclass -> UserGenerateLockfiles.
    """


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


class _ResolveProviderType(Enum):
    TOOL = 1
    USER = 2


@dataclass(frozen=True, order=True)
class _ResolveProvider:
    option_name: str
    type_: _ResolveProviderType


class AmbiguousResolveNamesError(Exception):
    def __init__(self, ambiguous_name: str, providers: set[_ResolveProvider]) -> None:
        tool_providers = []
        user_providers = []
        for provider in sorted(providers):
            if provider.type_ == _ResolveProviderType.TOOL:
                tool_providers.append(provider.option_name)
            else:
                user_providers.append(provider.option_name)

        if tool_providers:
            if not user_providers:
                raise AssertionError(
                    f"{len(tool_providers)} tools have the same options_scope: {ambiguous_name}. "
                    "If you're writing a plugin, rename your `GenerateToolLockfileSentinel`s so "
                    "that there is no ambiguity. Otherwise, please open a bug at "
                    "https://github.com/pantsbuild/pants/issues/new."
                )
            if len(user_providers) == 1:
                msg = (
                    f"A resolve name from the option `{user_providers[0]}` collides with the "
                    f"name of a tool resolve: {ambiguous_name}\n\n"
                    f"To fix, please update `{user_providers[0]}` to use a different resolve name."
                )
            else:
                msg = (
                    f"Multiple options define the resolve name `{ambiguous_name}`, but it is "
                    f"already claimed by a tool: {user_providers}\n\n"
                    f"To fix, please update these options so that none of them use "
                    f"`{ambiguous_name}`."
                )
        else:
            assert len(user_providers) > 1
            msg = (
                f"The same resolve name `{ambiguous_name}` is used by multiple options, which "
                f"causes ambiguity: {user_providers}\n\n"
                f"To fix, please update these options so that `{ambiguous_name}` is not used more "
                f"than once."
            )
        super().__init__(msg)


def _check_ambiguous_resolve_names(
    all_known_user_resolve_names: Iterable[KnownUserResolveNames],
    all_tool_sentinels: Iterable[type[GenerateToolLockfileSentinel]],
) -> None:
    resolve_name_to_providers = defaultdict(set)
    for sentinel in all_tool_sentinels:
        resolve_name_to_providers[sentinel.resolve_name].add(
            _ResolveProvider(sentinel.resolve_name, _ResolveProviderType.TOOL)
        )
    for known_user_resolve_names in all_known_user_resolve_names:
        for resolve_name in known_user_resolve_names.names:
            resolve_name_to_providers[resolve_name].add(
                _ResolveProvider(known_user_resolve_names.option_name, _ResolveProviderType.USER)
            )

    for resolve_name, providers in resolve_name_to_providers.items():
        if len(providers) > 1:
            raise AmbiguousResolveNamesError(resolve_name, providers)


def determine_resolves_to_generate(
    all_known_user_resolve_names: Iterable[KnownUserResolveNames],
    all_tool_sentinels: Iterable[type[GenerateToolLockfileSentinel]],
    requested_resolve_names: set[str],
) -> tuple[list[RequestedUserResolveNames], list[type[GenerateToolLockfileSentinel]]]:
    """Apply the `--resolve` option to determine which resolves are specified.

    Return a tuple of `(user_resolves, tool_lockfile_sentinels)`.
    """
    _check_ambiguous_resolve_names(all_known_user_resolve_names, all_tool_sentinels)

    resolve_names_to_sentinels = {
        sentinel.resolve_name: sentinel for sentinel in all_tool_sentinels
    }

    if not requested_resolve_names:
        return [
            known_resolve_names.requested_resolve_names_cls(known_resolve_names.names)
            for known_resolve_names in all_known_user_resolve_names
        ], list(all_tool_sentinels)

    requested_user_resolve_names = []
    for known_resolve_names in all_known_user_resolve_names:
        requested = requested_resolve_names.intersection(known_resolve_names.names)
        if requested:
            requested_resolve_names -= requested
            requested_user_resolve_names.append(
                known_resolve_names.requested_resolve_names_cls(requested)
            )

    specified_sentinels = []
    for resolve, sentinel in resolve_names_to_sentinels.items():
        if resolve in requested_resolve_names:
            requested_resolve_names.discard(resolve)
            specified_sentinels.append(sentinel)

    if requested_resolve_names:
        raise UnrecognizedResolveNamesError(
            unrecognized_resolve_names=sorted(requested_resolve_names),
            all_valid_names={
                *itertools.chain.from_iterable(
                    known_resolve_names.names
                    for known_resolve_names in all_known_user_resolve_names
                ),
                *resolve_names_to_sentinels.keys(),
            },
            description_of_origin="the option `--generate-lockfiles-resolve`",
        )

    return requested_user_resolve_names, specified_sentinels


def filter_tool_lockfile_requests(
    specified_requests: Sequence[WrappedGenerateLockfile], *, resolve_specified: bool
) -> list[GenerateLockfile]:
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


class GenerateLockfilesSubsystem(GoalSubsystem):
    name = "generate-lockfiles"
    help = "Generate lockfiles for Python third-party dependencies."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return (
            GenerateToolLockfileSentinel in union_membership
            or KnownUserResolveNamesRequest in union_membership
        )

    resolve_names = StrListOption(
        "--resolve",
        advanced=False,
        help=(
            "Only generate lockfiles for the specified resolve(s).\n\n"
            "Resolves are the logical names for the different lockfiles used in your project. "
            "For your own code's dependencies, these come from the option "
            "`[python].resolves`. For tool lockfiles, resolve "
            "names are the options scope for that tool such as `black`, `pytest`, and "
            "`mypy-protobuf`.\n\n"
            f"For example, you can run `{bin_name()} generate-lockfiles --resolve=black "
            "--resolve=pytest --resolve=data-science` to only generate lockfiles for those "
            "two tools and your resolve named `data-science`.\n\n"
            "If you specify an invalid resolve name, like 'fake', Pants will output all "
            "possible values.\n\n"
            "If not specified, Pants will generate lockfiles for all resolves."
        ),
    )
    custom_command = StrOption(
        "--custom-command",
        advanced=True,
        default=None,
        help=(
            "If set, lockfile headers will say to run this command to regenerate the lockfile, "
            f"rather than running `{bin_name()} generate-lockfiles --resolve=<name>` like normal."
        ),
    )


class GenerateLockfilesGoal(Goal):
    subsystem_cls = GenerateLockfilesSubsystem


@goal_rule
async def generate_lockfiles_goal(
    workspace: Workspace,
    union_membership: UnionMembership,
    generate_lockfiles_subsystem: GenerateLockfilesSubsystem,
) -> GenerateLockfilesGoal:
    known_user_resolve_names = await MultiGet(
        Get(KnownUserResolveNames, KnownUserResolveNamesRequest, request())
        for request in union_membership.get(KnownUserResolveNamesRequest)
    )
    requested_user_resolve_names, requested_tool_sentinels = determine_resolves_to_generate(
        known_user_resolve_names,
        union_membership.get(GenerateToolLockfileSentinel),
        set(generate_lockfiles_subsystem.resolve_names),
    )

    all_specified_user_requests = await MultiGet(
        Get(UserGenerateLockfiles, RequestedUserResolveNames, resolve_names)
        for resolve_names in requested_user_resolve_names
    )
    specified_tool_requests = await MultiGet(
        Get(WrappedGenerateLockfile, GenerateToolLockfileSentinel, sentinel())
        for sentinel in requested_tool_sentinels
    )
    applicable_tool_requests = filter_tool_lockfile_requests(
        specified_tool_requests,
        resolve_specified=bool(generate_lockfiles_subsystem.resolve_names),
    )

    results = await MultiGet(
        Get(GenerateLockfileResult, GenerateLockfile, req)
        for req in (
            *(req for reqs in all_specified_user_requests for req in reqs),
            *applicable_tool_requests,
        )
    )

    merged_digest = await Get(Digest, MergeDigests(res.digest for res in results))
    workspace.write_digest(merged_digest)
    for result in results:
        logger.info(f"Wrote lockfile for the resolve `{result.resolve_name}` to {result.path}")

    return GenerateLockfilesGoal(exit_code=0)


def rules():
    return collect_rules()
