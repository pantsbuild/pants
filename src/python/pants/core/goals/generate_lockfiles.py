# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import itertools
import logging
from dataclasses import dataclass, replace
from typing import Callable, Iterable, Iterator, Mapping, Protocol, Sequence, Tuple, cast

from pants.core.goals.resolve_helpers import (
    GenerateLockfile,
    GenerateToolLockfileSentinel,
    KnownUserResolveNamesRequest,
    WrappedGenerateLockfile,
    determine_requested_resolves,
)
from pants.engine.console import Console
from pants.engine.environment import ChosenLocalEnvironmentName, EnvironmentName
from pants.engine.fs import Digest, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import Get, MultiGet
from pants.engine.rules import collect_rules, goal_rule
from pants.engine.unions import UnionMembership
from pants.help.maybe_color import MaybeColor
from pants.option.global_options import GlobalOptions
from pants.option.option_types import BoolOption, StrListOption, StrOption
from pants.util.docutil import bin_name
from pants.util.frozendict import FrozenDict
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GenerateLockfileResult:
    """The result of generating a lockfile for a particular resolve."""

    digest: Digest
    resolve_name: str
    path: str
    diff: LockfileDiff | None = None


@dataclass(frozen=True)
class GenerateLockfileWithEnvironments(GenerateLockfile):
    """Allows a `GenerateLockfile` subclass to specify which environments the request is compatible
    with, if the relevant backend supports environments."""

    environments: tuple[EnvironmentName, ...]


class PackageVersion(Protocol):
    """Protocol for backend specific implementations, to support language-ecosystem-specific version
    formats and sort rules.

    May support the `int` properties `major`, `minor` and `micro` to color diff based on semantic
    step taken.
    """

    def __eq__(self, other) -> bool:
        ...

    def __gt__(self, other) -> bool:
        ...

    def __lt__(self, other) -> bool:
        ...

    def __str__(self) -> str:
        ...


PackageName = str
LockfilePackages = FrozenDict[PackageName, PackageVersion]
ChangedPackages = FrozenDict[PackageName, Tuple[PackageVersion, PackageVersion]]


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


def filter_tool_lockfile_requests(
    specified_requests: Sequence[WrappedGenerateLockfile], *, resolve_specified: bool
) -> list[GenerateLockfile]:
    result = []
    for wrapped_req in specified_requests:
        req = wrapped_req.request
        if req.lockfile_dest != DEFAULT_TOOL_LOCKFILE:
            result.append(req)
            continue
        if resolve_specified:
            resolve = req.resolve_name
            raise ValueError(
                softwrap(
                    f"""
                    You requested to generate a lockfile for {resolve} because
                    you included it in `--generate-lockfiles-resolve`, but
                    `[{resolve}].lockfile` is set to `{req.lockfile_dest}`
                    so a lockfile will not be generated.

                    If you would like to generate a lockfile for {resolve}, please
                    set `[{resolve}].lockfile` to the path where it should be
                    generated and run again.
                    """
                )
            )

    return result


class GenerateLockfilesSubsystem(GoalSubsystem):
    name = "generate-lockfiles"
    help = "Generate lockfiles for third-party dependencies."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return (
            GenerateToolLockfileSentinel in union_membership
            or KnownUserResolveNamesRequest in union_membership
        )

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
    all_specified_user_requests, specified_tool_requests = await determine_requested_resolves(
        generate_lockfiles_subsystem.resolve, local_environment, union_membership
    )
    applicable_tool_requests = filter_tool_lockfile_requests(
        specified_tool_requests,
        resolve_specified=bool(generate_lockfiles_subsystem.resolve),
    )

    # Execute the actual lockfile generation in each request's environment.
    # Currently, since resolves specify a single filename for output, we pick a reasonable
    # environment to execute the request in. Currently we warn if multiple environments are
    # specified.
    all_requests: Iterator[GenerateLockfile] = itertools.chain(
        *all_specified_user_requests, applicable_tool_requests
    )
    if generate_lockfiles_subsystem.request_diffs:
        all_requests = (replace(req, diff=True) for req in all_requests)

    results = await MultiGet(
        Get(
            GenerateLockfileResult,
            {
                req: GenerateLockfile,
                _preferred_environment(req, local_environment.val): EnvironmentName,
            },
        )
        for req in all_requests
    )

    # Lockfiles are actually written here. This would be an acceptable place to handle conflict
    # resolution behaviour if we start executing requests in multiple environments.
    merged_digest = await Get(Digest, MergeDigests(res.digest for res in results))
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


def rules():
    return collect_rules()
