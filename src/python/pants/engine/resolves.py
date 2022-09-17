# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Iterable, Sequence

from pants.engine.collection import Collection
from pants.engine.environment import EnvironmentName
from pants.engine.rules import collect_rules
from pants.engine.target import Target
from pants.engine.unions import union
from pants.util.docutil import doc_url
from pants.util.strutil import bullet_list, softwrap

logger = logging.getLogger(__name__)


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
            softwrap(
                f"""
            Unrecognized resolve {name_description} from {description_of_origin}:
            {unrecognized_str}\n\nAll valid resolve names: {sorted(all_valid_names)}
            """
            )
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
                    softwrap(
                        f"""
                        {len(tool_providers)} tools have the same options_scope: {ambiguous_name}.
                        If you're writing a plugin, rename your `GenerateToolLockfileSentinel`s so
                        that there is no ambiguity. Otherwise, please open a bug at
                        https://github.com/pantsbuild/pants/issues/new.
                        """
                    )
                )
            if len(user_providers) == 1:
                msg = softwrap(
                    f"""
                    A resolve name from the option `{user_providers[0]}` collides with the
                    name of a tool resolve: {ambiguous_name}

                    To fix, please update `{user_providers[0]}` to use a different resolve name.
                    """
                )
            else:
                msg = softwrap(
                    f"""
                    Multiple options define the resolve name `{ambiguous_name}`, but it is
                    already claimed by a tool: {user_providers}

                    To fix, please update these options so that none of them use
                    `{ambiguous_name}`.
                    """
                )
        else:
            assert len(user_providers) > 1
            msg = softwrap(
                f"""
                The same resolve name `{ambiguous_name}` is used by multiple options, which
                causes ambiguity: {user_providers}

                To fix, please update these options so that `{ambiguous_name}` is not used more
                than once.
                """
            )
        super().__init__(msg)


# -----------------------------------------------------------------------------------------------
# Helpers for determining the resolve
# -----------------------------------------------------------------------------------------------


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
            The input targets did not have a resolve in common.\n\n
            {formatted_resolve_lists}\n\n
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


def rules():
    return collect_rules()
