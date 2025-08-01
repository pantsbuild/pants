# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import Enum
from typing import Protocol, cast

from pants.core.goals.resolves import ExportableTool
from pants.engine.collection import Collection, DeduplicatedCollection
from pants.engine.console import Console
from pants.engine.environment import ChosenLocalEnvironmentName, EnvironmentName
from pants.engine.fs import Digest, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import concurrently
from pants.engine.intrinsics import merge_digests
from pants.engine.rules import collect_rules, goal_rule, implicitly, rule
from pants.engine.target import Target
from pants.engine.unions import UnionMembership, union
from pants.help.maybe_color import MaybeColor
from pants.option.global_options import GlobalOptions
from pants.option.option_types import BoolOption, StrListOption, StrOption
from pants.util.docutil import bin_name, doc_url
from pants.util.frozendict import FrozenDict
from pants.util.strutil import bullet_list, softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerateLockfileResult:
    """The result of generating a lockfile for a particular resolve."""

    digest: Digest
    resolve_name: str
    path: str
    diff: LockfileDiff | None = None


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


@rule(polymorphic=True)
async def generate_lockfile(
    req: GenerateLockfile, env_name: EnvironmentName
) -> GenerateLockfileResult:
    raise NotImplementedError()


@dataclass(frozen=True)
class GenerateLockfileWithEnvironments(GenerateLockfile):
    """Allows a `GenerateLockfile` subclass to specify which environments the request is compatible
    with, if the relevant backend supports environments."""

    environments: tuple[EnvironmentName, ...]


@dataclass(frozen=True)
class WrappedGenerateLockfile:
    request: GenerateLockfile


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


@rule(polymorphic=True)
async def get_known_user_resolve_names(req: KnownUserResolveNamesRequest) -> KnownUserResolveNames:
    raise NotImplementedError()


@union(in_scope_types=[EnvironmentName])
class RequestedUserResolveNames(DeduplicatedCollection[str]):
    """The user resolves requested for a particular language ecosystem.

    Each language ecosystem should set up a subclass and register it with a UnionRule. Implement a
    rule that goes from the subclass -> UserGenerateLockfiles.
    """

    sort_input = True


@rule(polymorphic=True)
async def get_user_generate_lockfiles(
    req: RequestedUserResolveNames, env_name: EnvironmentName
) -> UserGenerateLockfiles:
    raise NotImplementedError()


class PackageVersion(Protocol):
    """Protocol for backend specific implementations, to support language-ecosystem-specific version
    formats and sort rules.

    May support the `int` properties `major`, `minor` and `micro` to color diff based on semantic
    step taken.
    """

    def __eq__(self, other) -> bool: ...

    def __gt__(self, other) -> bool: ...

    def __lt__(self, other) -> bool: ...

    def __str__(self) -> str: ...


PackageName = str
LockfilePackages = FrozenDict[PackageName, PackageVersion]
ChangedPackages = FrozenDict[PackageName, tuple[PackageVersion, PackageVersion]]


@dataclass(frozen=True)
class LockfileDiff:
    path: str
    resolve_name: str
    added: LockfilePackages
    downgraded: ChangedPackages
    removed: LockfilePackages
    unchanged: LockfilePackages
    upgraded: ChangedPackages

    @classmethod
    def create(
        cls, path: str, resolve_name: str, old: LockfilePackages, new: LockfilePackages
    ) -> LockfileDiff:
        diff = {
            name: (old[name], new[name])
            for name in sorted({*old.keys(), *new.keys()})
            if name in old and name in new
        }
        return cls(
            path=path,
            resolve_name=resolve_name,
            added=cls.__get_lockfile_packages(new, old),
            downgraded=cls.__get_changed_packages(diff, lambda prev, curr: prev > curr),
            removed=cls.__get_lockfile_packages(old, new),
            unchanged=LockfilePackages(
                {name: curr for name, (prev, curr) in diff.items() if prev == curr}
            ),
            upgraded=cls.__get_changed_packages(diff, lambda prev, curr: prev < curr),
        )

    @staticmethod
    def __get_lockfile_packages(
        src: Mapping[str, PackageVersion], exclude: Iterable[str]
    ) -> LockfilePackages:
        return LockfilePackages(
            {name: version for name, version in src.items() if name not in exclude}
        )

    @staticmethod
    def __get_changed_packages(
        src: Mapping[str, tuple[PackageVersion, PackageVersion]],
        predicate: Callable[[PackageVersion, PackageVersion], bool],
    ) -> ChangedPackages:
        return ChangedPackages(
            {name: prev_curr for name, prev_curr in src.items() if predicate(*prev_curr)}
        )


class LockfileDiffPrinter(MaybeColor):
    def __init__(self, console: Console, color: bool, include_unchanged: bool) -> None:
        super().__init__(color)
        self.console = console
        self.include_unchanged = include_unchanged

    def print(self, diff: LockfileDiff) -> None:
        output = "\n".join(self.output_sections(diff))
        if not output:
            return
        self.console.print_stderr(
            self.style(" " * 66, style="underline")
            + f"\nLockfile diff: {diff.path} [{diff.resolve_name}]\n"
            + output
        )

    def output_sections(self, diff: LockfileDiff) -> Iterator[str]:
        if self.include_unchanged:
            yield from self.output_reqs("Unchanged dependencies", diff.unchanged, fg="blue")
        yield from self.output_changed("Upgraded dependencies", diff.upgraded)
        yield from self.output_changed("!! Downgraded dependencies !!", diff.downgraded)
        yield from self.output_reqs("Added dependencies", diff.added, fg="green", style="bold")
        yield from self.output_reqs("Removed dependencies", diff.removed, fg="magenta")

    def style(self, text: str, **kwargs) -> str:
        return cast(str, self.maybe_color(text, **kwargs))

    def title(self, text: str) -> str:
        heading = f"== {text:^60} =="
        return self.style("\n".join((" " * len(heading), heading, "")), style="underline")

    def output_reqs(self, heading: str, reqs: LockfilePackages, **kwargs) -> Iterator[str]:
        if not reqs:
            return

        yield self.title(heading)
        for name, version in reqs.items():
            name_s = self.style(f"{name:30}", fg="yellow")
            version_s = self.style(str(version), **kwargs)
            yield f"  {name_s} {version_s}"

    def output_changed(self, title: str, reqs: ChangedPackages) -> Iterator[str]:
        if not reqs:
            return

        yield self.title(title)
        label = "-->"
        for name, (prev, curr) in reqs.items():
            bump_attrs = self.get_bump_attrs(prev, curr)
            name_s = self.style(f"{name:30}", fg="yellow")
            prev_s = self.style(f"{str(prev):10}", fg="cyan")
            bump_s = self.style(f"{label:^7}", **bump_attrs)
            curr_s = self.style(str(curr), **bump_attrs)
            yield f"  {name_s} {prev_s} {bump_s} {curr_s}"

    _BUMPS = (
        ("major", dict(fg="red", style="bold")),
        ("minor", dict(fg="yellow")),
        ("micro", dict(fg="green")),
        # Default style
        (None, dict(fg="magenta")),
    )

    def get_bump_attrs(self, prev: PackageVersion, curr: PackageVersion) -> dict[str, str]:
        for key, attrs in self._BUMPS:
            if key is None or getattr(prev, key, None) != getattr(curr, key, None):
                return attrs
        return {}  # Should never happen, but let's be safe.


DEFAULT_TOOL_LOCKFILE = "<default>"


class UnrecognizedResolveNamesError(Exception):
    def __init__(
        self,
        unrecognized_resolve_names: list[str],
        all_valid_names: Iterable[str],
        all_valid_binaries: Iterable[str] | None = None,
        *,
        description_of_origin: str,
    ) -> None:
        all_valid_binaries = all_valid_binaries or set()

        # TODO(#12314): maybe implement "Did you mean?"
        if len(unrecognized_resolve_names) == 1:
            unrecognized_str = unrecognized_resolve_names[0]
            name_description = "name"
        else:
            unrecognized_str = str(sorted(unrecognized_resolve_names))
            name_description = "names"

        message = [
            f"Unrecognized resolve {name_description} from {description_of_origin}: {unrecognized_str}",
            f"All valid resolve names: {sorted(all_valid_names)}",
        ]
        if all_valid_binaries:
            message.append(f"All valid exportable binaries: {sorted(all_valid_binaries)}")

        should_be_bins = set(unrecognized_resolve_names) & set(all_valid_binaries)
        should_be_resolves = set(unrecognized_resolve_names) & set(all_valid_names)

        if should_be_bins:
            cmd = " ".join([f"--bin={e}" for e in should_be_bins])
            message.append(f"HINT: Some resolves should be binaries, try with `{cmd}`")

        if should_be_resolves:
            cmd = " ".join([f"--resolve={e}" for e in should_be_resolves])
            message.append(f"HINT: Some binaries should be resolves, try with `{cmd}`")

        super().__init__(softwrap("\n\n".join(message)))


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
    requested_resolve_names: set[str],
) -> list[RequestedUserResolveNames]:
    """Apply the `--resolve` option to determine which resolves are specified."""
    # Resolve names must be globally unique, so check for ambiguity across backends.
    _check_ambiguous_resolve_names(all_known_user_resolve_names)

    # If no resolves have been requested, we generate lockfiles for all user resolves
    if not requested_resolve_names:
        return [
            known_resolve_names.requested_resolve_names_cls(known_resolve_names.names)
            for known_resolve_names in all_known_user_resolve_names
        ]

    requested_user_resolve_names = []
    for known_resolve_names in all_known_user_resolve_names:
        requested = requested_resolve_names.intersection(known_resolve_names.names)
        if requested:
            requested_resolve_names -= requested
            requested_user_resolve_names.append(
                known_resolve_names.requested_resolve_names_cls(requested)
            )

    if requested_resolve_names:
        raise UnrecognizedResolveNamesError(
            unrecognized_resolve_names=sorted(requested_resolve_names),
            all_valid_names={
                *itertools.chain.from_iterable(
                    known_resolve_names.names
                    for known_resolve_names in all_known_user_resolve_names
                ),
            },
            description_of_origin="the option `--generate-lockfiles-resolve`",
        )

    return requested_user_resolve_names


def filter_lockfiles_for_unconfigured_exportable_tools(
    generate_lockfile_requests: Sequence[GenerateLockfile],
    exportabletools_by_name: dict[str, type[ExportableTool]],
    *,
    resolve_specified: bool,
) -> tuple[tuple[str, ...], tuple[GenerateLockfile, ...]]:
    """Filter lockfile requests for tools still using their default lockfiles."""

    valid_lockfiles = []
    errs = []

    for req in generate_lockfile_requests:
        if req.lockfile_dest != DEFAULT_TOOL_LOCKFILE:
            valid_lockfiles.append(req)
            continue

        if req.resolve_name in exportabletools_by_name:
            if resolve_specified:
                # A user has asked us to generate a tool which is using a default lockfile
                errs.append(
                    exportabletools_by_name[
                        req.resolve_name
                    ].help_for_generate_lockfile_with_default_location(req.resolve_name)
                )
            else:
                # When a user selects no resolves, we try generating lockfiles for all resolves.
                # The intention is clearly to not generate lockfiles for internal tools, so we skip them here.
                continue
        else:
            # Arriving at this case is either a user error or an implementation error, but we can be helpful
            errs.append(
                softwrap(
                    f"""
                    The resolve {req.resolve_name} is using the lockfile destination {DEFAULT_TOOL_LOCKFILE}.
                    This destination is used as a sentinel to signal that internal tools should use their bundled lockfile.
                    However, the resolve {req.resolve_name} does not appear to be an exportable tool.

                    If you intended to generate a lockfile for a resolve you specified,
                    you should specify a file as the lockfile destination.
                    If this is indeed a tool that should be exportable, this is a bug:
                    This tool does not appear to be exportable the way we expect.
                    It may need a `UnionRule` to `ExportableTool`
                    """
                )
            )
            continue

    return tuple(errs), tuple(valid_lockfiles)


class GenerateLockfilesSubsystem(GoalSubsystem):
    name = "generate-lockfiles"
    help = "Generate lockfiles for third-party dependencies."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return KnownUserResolveNamesRequest in union_membership

    resolve = StrListOption(
        advanced=False,
        help=softwrap(
            f"""
            Only generate lockfiles for the specified resolve(s).

            Resolves are the logical names for the different lockfiles used in your project.
            For your own code's dependencies, these come from backend-specific configuration
            such as `[python].resolves`. For tool lockfiles, resolve names are the options
            scope for that tool such as `black`, `pytest`, and `mypy-protobuf`.

            For example, you can run `{bin_name()} generate-lockfiles --resolve=black
            --resolve=pytest --resolve=data-science` to only generate lockfiles for those
            two tools and your resolve named `data-science`.

            If you specify an invalid resolve name, like 'fake', Pants will output all
            possible values.

            If not specified, Pants will generate lockfiles for all resolves.
            """
        ),
    )
    custom_command = StrOption(
        advanced=True,
        default=None,
        help=softwrap(
            f"""
            If set, lockfile headers will say to run this command to regenerate the lockfile,
            rather than running `{bin_name()} generate-lockfiles --resolve=<name>` like normal.
            """
        ),
    )
    diff = BoolOption(
        default=True,
        help=softwrap(
            """
            Print a summary of changed distributions after generating the lockfile.
            """
        ),
    )
    diff_include_unchanged = BoolOption(
        default=False,
        help=softwrap(
            """
            Include unchanged distributions in the diff summary output. Implies `diff=true`.
            """
        ),
    )

    @property
    def request_diffs(self) -> bool:
        return self.diff or self.diff_include_unchanged


class GenerateLockfilesGoal(Goal):
    subsystem_cls = GenerateLockfilesSubsystem
    environment_behavior = Goal.EnvironmentBehavior.USES_ENVIRONMENTS


@goal_rule
async def generate_lockfiles_goal(
    workspace: Workspace,
    union_membership: UnionMembership,
    generate_lockfiles_subsystem: GenerateLockfilesSubsystem,
    local_environment: ChosenLocalEnvironmentName,
    console: Console,
    global_options: GlobalOptions,
) -> GenerateLockfilesGoal:
    known_user_resolve_names = await concurrently(
        get_known_user_resolve_names(**implicitly({request(): KnownUserResolveNamesRequest}))
        for request in union_membership.get(KnownUserResolveNamesRequest)
    )
    requested_user_resolve_names = determine_resolves_to_generate(
        known_user_resolve_names,
        set(generate_lockfiles_subsystem.resolve),
    )

    # This is the "planning" phase of lockfile generation. Currently this is all done in the local
    # environment, since there's not currently a clear mechanism to prescribe an environment.
    all_specified_user_requests = await concurrently(
        get_user_generate_lockfiles(
            **implicitly(
                {resolve_names: RequestedUserResolveNames, local_environment.val: EnvironmentName}
            )
        )
        for resolve_names in requested_user_resolve_names
    )
    resolve_specified = bool(generate_lockfiles_subsystem.resolve)
    # We filter "user" requests because we're moving to combine user and tool lockfiles
    (
        tool_request_errors,
        applicable_user_requests,
    ) = filter_lockfiles_for_unconfigured_exportable_tools(
        list(itertools.chain(*all_specified_user_requests)),
        {e.options_scope: e for e in union_membership.get(ExportableTool)},
        resolve_specified=resolve_specified,
    )

    if tool_request_errors:
        raise ValueError("\n\n".join(tool_request_errors))

    # Execute the actual lockfile generation in each request's environment.
    # Currently, since resolves specify a single filename for output, we pick a reasonable
    # environment to execute the request in. Currently we warn if multiple environments are
    # specified.
    if generate_lockfiles_subsystem.request_diffs:
        all_requests = tuple(replace(req, diff=True) for req in applicable_user_requests)
    else:
        all_requests = applicable_user_requests

    results = await concurrently(
        generate_lockfile(
            **implicitly(
                {
                    req: GenerateLockfile,
                    _preferred_environment(req, local_environment.val): EnvironmentName,
                }
            )
        )
        for req in all_requests
    )

    # Lockfiles are actually written here. This would be an acceptable place to handle conflict
    # resolution behaviour if we start executing requests in multiple environments.
    merged_digest = await merge_digests(MergeDigests(res.digest for res in results))
    workspace.write_digest(merged_digest)

    diffs: list[LockfileDiff] = []
    for result in results:
        logger.info(f"Wrote lockfile for the resolve `{result.resolve_name}` to {result.path}")
        if result.diff is not None:
            diffs.append(result.diff)

    if diffs:
        diff_formatter = LockfileDiffPrinter(
            console=console,
            color=global_options.colors,
            include_unchanged=generate_lockfiles_subsystem.diff_include_unchanged,
        )
        for diff in diffs:
            diff_formatter.print(diff)
        console.print_stderr("\n")

    return GenerateLockfilesGoal(exit_code=0)


def _preferred_environment(request: GenerateLockfile, default: EnvironmentName) -> EnvironmentName:
    if not isinstance(request, GenerateLockfileWithEnvironments):
        return default  # This request has not been migrated to use environments.

    if len(request.environments) == 1:
        return request.environments[0]

    ret = default if default in request.environments else request.environments[0]

    logger.warning(
        f"The `{request.__class__.__name__}` for resolve `{request.resolve_name}` specifies more "
        "than one environment. Pants will generate the lockfile using only the environment "
        f"`{ret.val}`, which may have unintended effects when executing in the other environments."
    )

    return ret


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


def rules():
    return collect_rules()
