# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Callable, ClassVar, Iterable, Sequence, Tuple

from pants.engine.collection import Collection
from pants.engine.environment import ChosenLocalEnvironmentName, EnvironmentName
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, rule
from pants.engine.target import Target
from pants.engine.unions import UnionMembership, union
from pants.util.docutil import doc_url
from pants.util.strutil import bullet_list, softwrap

logger = logging.getLogger(__name__)


@union(in_scope_types=[EnvironmentName])
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
    diff: bool


@union(in_scope_types=[EnvironmentName])
class GenerateToolLockfileSentinel:
    """Tools use this as an entry point to say how to generate their tool lockfile.

    Each language ecosystem should set up a union member of `GenerateLockfile`, like
    `GeneratePythonLockfile`, as explained in that class's docstring.

    Each language ecosystem should also subclass `GenerateToolLockfileSentinel`, e.g.
    `GeneratePythonToolLockfileSentinel`. The subclass does not need to do anything - it is only used to know which language ecosystems tools correspond to.

    Then, each tool should subclass their language ecosystem's subclass of `GenerateToolLockfileSentinel` and set up a rule that goes from the
    subclass -> the language's lockfile request, e.g. BlackLockfileSentinel ->
    GeneratePythonLockfile. Register `UnionRule(GenerateToolLockfileSentinel, MySubclass)`.
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


@union(in_scope_types=[EnvironmentName])
class RequestedUserResolveNames(Collection[str]):
    """The user resolves requested for a particular language ecosystem.

    Each language ecosystem should set up a subclass and register it with a UnionRule. Implement a
    rule that goes from the subclass -> UserGenerateLockfiles.
    """


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
            softwrap(
                f"""
                Unrecognized resolve {name_description} from {description_of_origin}:
                {unrecognized_str}

                All valid resolve names: {sorted(all_valid_names)}
                """
            )
        )


class _ResolveProviderType(Enum):
    TOOL = 1
    USER = 2


@dataclass(frozen=True, order=True)
class _ResolveProvider:
    option_name: str


class AmbiguousResolveNamesError(Exception):
    def __init__(self, ambiguous_name: str, providers: set[_ResolveProvider]) -> None:
        msg = softwrap(
            f"""
            The same resolve name `{ambiguous_name}` is used by multiple options, which
            causes ambiguity: {providers}

            To fix, please update these options so that `{ambiguous_name}` is not used more
            than once.
            """
        )
        super().__init__(msg)


def _check_ambiguous_resolve_names(
    all_known_user_resolve_names: Iterable[KnownUserResolveNames],
) -> None:
    resolve_name_to_providers = defaultdict(set)
    for known_user_resolve_names in all_known_user_resolve_names:
        for resolve_name in known_user_resolve_names.names:
            resolve_name_to_providers[resolve_name].add(
                _ResolveProvider(known_user_resolve_names.option_name)
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
    # Let user resolve names silently shadow tools with the same name.
    # This is necessary since we now support installing a tool from a named resolve,
    # and it's not reasonable to ban the name of the tool as the resolve name, when it
    # is the most obvious choice for that...
    # This is likely only an issue if you were going to, e.g., have a named resolve called flake8
    # but not use it as the resolve for the flake8 tool, which seems pretty unlikely.
    all_known_user_resolve_name_strs = set(
        itertools.chain.from_iterable(akurn.names for akurn in all_known_user_resolve_names)
    )
    all_tool_sentinels = [
        ts for ts in all_tool_sentinels if ts.resolve_name not in all_known_user_resolve_name_strs
    ]

    # Resolve names must be globally unique, so check for ambiguity across backends.
    _check_ambiguous_resolve_names(all_known_user_resolve_names)

    if not requested_resolve_names:
        return [
            known_resolve_names.requested_resolve_names_cls(known_resolve_names.names)
            for known_resolve_names in all_known_user_resolve_names
        ], list(all_tool_sentinels)

    requested_user_resolve_names = []
    logger.debug(
        f"searching for requested resolves {requested_resolve_names=} {all_known_user_resolve_names=}"
    )
    for known_resolve_names in all_known_user_resolve_names:
        requested = requested_resolve_names.intersection(known_resolve_names.names)
        if requested:
            requested_resolve_names -= requested
            requested_user_resolve_names.append(
                known_resolve_names.requested_resolve_names_cls(requested)
            )

    specified_sentinels = []
    for sentinel in all_tool_sentinels:
        if sentinel.resolve_name in requested_resolve_names:
            requested_resolve_names.discard(sentinel.resolve_name)
            specified_sentinels.append(sentinel)

    if requested_resolve_names:
        raise UnrecognizedResolveNamesError(
            unrecognized_resolve_names=sorted(requested_resolve_names),
            all_valid_names={
                *itertools.chain.from_iterable(
                    known_resolve_names.names
                    for known_resolve_names in all_known_user_resolve_names
                ),
                *(sentinel.resolve_name for sentinel in all_tool_sentinels),
            },
            description_of_origin="the option `--generate-lockfiles-resolve`",
        )

    return requested_user_resolve_names, specified_sentinels


class NoCompatibleResolveException(Exception):
    """No compatible resolve could be found for a set of targets."""

    @classmethod
    def bad_input_roots(
        cls,
        targets: Iterable[Target],
        *,
        maybe_get_resolve: Callable[[Target], str | None],
        doc_url_slug: str,
        workaround: str | None,
    ) -> NoCompatibleResolveException:
        resolves_to_addresses = defaultdict(list)
        for tgt in targets:
            maybe_resolve = maybe_get_resolve(tgt)
            if maybe_resolve is not None:
                resolves_to_addresses[maybe_resolve].append(tgt.address.spec)

        formatted_resolve_lists = "\n\n".join(
            f"{resolve}:\n{bullet_list(sorted(addresses))}"
            for resolve, addresses in sorted(resolves_to_addresses.items())
        )
        return NoCompatibleResolveException(
            softwrap(
                f"""
                The input targets did not have a resolve in common.

                {formatted_resolve_lists}

                Targets used together must use the same resolve, set by the `resolve` field. For more
                information on 'resolves' (lockfiles), see {doc_url(doc_url_slug)}.
                """
            )
            + (f"\n\n{workaround}" if workaround else "")
        )

    @classmethod
    def bad_dependencies(
        cls,
        *,
        maybe_get_resolve: Callable[[Target], str | None],
        doc_url_slug: str,
        root_resolve: str,
        root_targets: Sequence[Target],
        dependencies: Iterable[Target],
    ) -> NoCompatibleResolveException:
        if len(root_targets) == 1:
            addr = root_targets[0].address
            prefix = softwrap(
                f"""
                The target {addr} uses the `resolve` `{root_resolve}`, but some of its
                dependencies are not compatible with that resolve:
                """
            )
            change_input_targets_instructions = f"of the target {addr}"
        else:
            assert root_targets
            prefix = softwrap(
                f"""
                The input targets use the `resolve` `{root_resolve}`, but some of their
                dependencies are not compatible with that resolve.

                Input targets:

                {bullet_list(sorted(t.address.spec for t in root_targets))}

                Bad dependencies:
                """
            )
            change_input_targets_instructions = "of the input targets"

        deps_strings = []
        for dep in dependencies:
            maybe_resolve = maybe_get_resolve(dep)
            if maybe_resolve is None or maybe_resolve == root_resolve:
                continue
            deps_strings.append(f"{dep.address} ({maybe_resolve})")

        return NoCompatibleResolveException(
            softwrap(
                f"""
                {prefix}

                {bullet_list(deps_strings)}

                All dependencies must work with the same `resolve`. To fix this, either change
                the `resolve=` field on those dependencies to `{root_resolve}`, or change
                the `resolve=` {change_input_targets_instructions}. If those dependencies should
                work with multiple resolves, use the `parametrize` mechanism with the `resolve=`
                field or manually create multiple targets for the same entity.

                For more information, see {doc_url(doc_url_slug)}.
                """
            )
        )


@dataclass(frozen=True)
class WrappedGenerateLockfile:
    request: GenerateLockfile


@dataclass(frozen=True)
class RequestedResolvesNames:
    val: Tuple[str, ...]


@dataclass(frozen=True)
class RequestedResolves:
    user_requests: Tuple[UserGenerateLockfiles, ...]
    tool_requests: Tuple[WrappedGenerateLockfile, ...]


@rule
async def determine_requested_resolves(
    requested_resolves: RequestedResolvesNames,
    local_environment: ChosenLocalEnvironmentName,
    union_membership: UnionMembership,
) -> RequestedResolves:
    known_user_resolve_names = await MultiGet(
        Get(KnownUserResolveNames, KnownUserResolveNamesRequest, request())
        for request in union_membership.get(KnownUserResolveNamesRequest)
    )
    logger.debug(f"Found known user resolves {known_user_resolve_names}")
    requested_user_resolve_names, requested_tool_sentinels = determine_resolves_to_generate(
        known_user_resolve_names,
        union_membership.get(GenerateToolLockfileSentinel),
        set(requested_resolves.val),
    )
    # This is the "planning" phase of lockfile generation. Currently this is all done in the local
    # environment, since there's not currently a clear mechanism to prescribe an environment.
    all_specified_user_requests = await MultiGet(
        Get(
            UserGenerateLockfiles,
            {resolve_names: RequestedUserResolveNames, local_environment.val: EnvironmentName},
        )
        for resolve_names in requested_user_resolve_names
    )
    logger.debug(f"Identified specified user requests as {all_specified_user_requests}")
    specified_tool_requests = await MultiGet(
        Get(
            WrappedGenerateLockfile,
            {sentinel(): GenerateToolLockfileSentinel, local_environment.val: EnvironmentName},
        )
        for sentinel in requested_tool_sentinels
    )
    return RequestedResolves(all_specified_user_requests, specified_tool_requests)


def rules():
    return collect_rules()
