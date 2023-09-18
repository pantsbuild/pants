# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
from abc import ABC
from dataclasses import dataclass
from typing import ClassVar, Iterable, Mapping, Optional, Sequence, Tuple

from pants.core.util_rules.environments import _warn_on_non_local_environments
from pants.engine.addresses import Addresses
from pants.engine.console import Console
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.environment import EnvironmentName
from pants.engine.fs import Digest
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
from pants.engine.rules import Effect, Get, collect_rules, goal_rule
from pants.engine.target import FilteredTargets, Target
from pants.engine.unions import UnionMembership, union
from pants.option.option_types import ArgsListOption, BoolOption, StrOption
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized_property
from pants.util.strutil import softwrap


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class ReplImplementation(ABC):
    """A REPL implementation for a specific language or runtime.

    Proxies from the top-level `repl` goal to an actual implementation.
    """

    name: ClassVar[str]

    targets: Sequence[Target]

    def in_chroot(self, relpath: str) -> str:
        return os.path.join("{chroot}", relpath)

    @memoized_property
    def addresses(self) -> Addresses:
        return Addresses(t.address for t in self.targets)


class ReplSubsystem(GoalSubsystem):
    name = "repl"
    help = "Open a REPL with the specified code loadable."

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return ReplImplementation in union_membership

    shell = StrOption(
        default=None,
        help="Override the automatically-detected REPL program for the target(s) specified.",
    )
    args = ArgsListOption(
        example="-i helloworld/main.py",
        tool_name="the repl program",
        passthrough=True,
    )
    restartable = BoolOption(
        default=False,
        help="True if the REPL should be restarted if its inputs have changed.",
    )


class Repl(Goal):
    subsystem_cls = ReplSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


@dataclass(frozen=True)
class ReplRequest:
    digest: Digest
    args: Tuple[str, ...]
    extra_env: FrozenDict[str, str]
    immutable_input_digests: FrozenDict[str, Digest]
    append_only_caches: FrozenDict[str, str]
    run_in_workspace: bool

    def __init__(
        self,
        *,
        digest: Digest,
        args: Iterable[str],
        extra_env: Optional[Mapping[str, str]] = None,
        immutable_input_digests: Mapping[str, Digest] | None = None,
        append_only_caches: Mapping[str, str] | None = None,
        run_in_workspace: bool = True,
    ) -> None:
        object.__setattr__(self, "digest", digest)
        object.__setattr__(self, "args", tuple(args))
        object.__setattr__(self, "extra_env", FrozenDict(extra_env or {}))
        object.__setattr__(
            self, "immutable_input_digests", FrozenDict(immutable_input_digests or {})
        )
        object.__setattr__(self, "append_only_caches", FrozenDict(append_only_caches or {}))
        object.__setattr__(self, "run_in_workspace", run_in_workspace)


@goal_rule
async def run_repl(
    console: Console,
    repl_subsystem: ReplSubsystem,
    specified_targets: FilteredTargets,
    union_membership: UnionMembership,
    complete_env: CompleteEnvironmentVars,
) -> Repl:
    await _warn_on_non_local_environments(specified_targets, "the `repl` goal")

    # TODO: When we support multiple languages, detect the default repl to use based
    #  on the targets.  For now we default to the python repl.
    repl_shell_name = repl_subsystem.shell or "python"
    implementations = {impl.name: impl for impl in union_membership[ReplImplementation]}
    repl_implementation_cls = implementations.get(repl_shell_name)
    if repl_implementation_cls is None:
        available = sorted(implementations.keys())
        console.print_stderr(
            softwrap(
                f"""
                {repr(repl_shell_name)} is not a registered REPL. Available REPLs (which may
                be specified through the option `--repl-shell`): {available}
                """
            )
        )
        return Repl(-1)

    repl_impl = repl_implementation_cls(targets=specified_targets)
    request = await Get(ReplRequest, ReplImplementation, repl_impl)

    env = {**complete_env, **request.extra_env}
    result = await Effect(
        InteractiveProcessResult,
        InteractiveProcess(
            argv=(*request.args, *repl_subsystem.args),
            env=env,
            input_digest=request.digest,
            run_in_workspace=request.run_in_workspace,
            restartable=repl_subsystem.restartable,
            immutable_input_digests=request.immutable_input_digests,
            append_only_caches=request.append_only_caches,
        ),
    )
    return Repl(result.exit_code)


def rules():
    return collect_rules()
