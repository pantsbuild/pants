# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
from abc import ABCMeta
from dataclasses import dataclass
from itertools import filterfalse, tee
from typing import Callable, Iterable, Mapping, NamedTuple, Optional, Tuple, TypeVar

from pants.base.build_root import BuildRoot
from pants.core.subsystems.debug_adapter import DebugAdapterSubsystem
from pants.core.util_rules.environments import _warn_on_non_local_environments
from pants.engine.env_vars import CompleteEnvironmentVars
from pants.engine.environment import EnvironmentName
from pants.engine.fs import Digest, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.specs_rules import (
    AmbiguousImplementationsException,
    TooManyTargetsException,
)
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
from pants.engine.rules import Effect, Get, collect_rules, goal_rule, rule_helper
from pants.engine.target import (
    BoolField,
    FieldSet,
    NoApplicableTargetsBehavior,
    SecondaryOwnerMixin,
    Target,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import UnionMembership, union
from pants.option.global_options import GlobalOptions, KeepSandboxes
from pants.option.option_types import ArgsListOption, BoolOption
from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init
from pants.util.strutil import softwrap

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


@union(in_scope_types=[EnvironmentName])
class RunFieldSet(FieldSet, metaclass=ABCMeta):
    """The fields necessary from a target to run a program/script."""


class RestartableField(BoolField):
    alias = "restartable"
    default = False
    help = softwrap(
        """
        If true, runs of this target with the `run` goal may be interrupted and
        restarted when its input files change.
        """
    )


@frozen_after_init
@dataclass(unsafe_hash=True)
class RunRequest:
    digest: Digest
    # Values in args and in env can contain the format specifier "{chroot}", which will
    # be substituted with the (absolute) chroot path.
    args: Tuple[str, ...]
    extra_env: FrozenDict[str, str]
    immutable_input_digests: Mapping[str, Digest] | None = None
    append_only_caches: Mapping[str, str] | None = None

    def __init__(
        self,
        *,
        digest: Digest,
        args: Iterable[str],
        extra_env: Optional[Mapping[str, str]] = None,
        immutable_input_digests: Mapping[str, Digest] | None = None,
        append_only_caches: Mapping[str, str] | None = None,
    ) -> None:
        self.digest = digest
        self.args = tuple(args)
        self.extra_env = FrozenDict(extra_env or {})
        self.immutable_input_digests = immutable_input_digests
        self.append_only_caches = append_only_caches


class RunDebugAdapterRequest(RunRequest):
    """Like RunRequest, but launches the process using the relevant Debug Adapter server.

    The process should be launched waiting for the client to connect.
    """


class RunSubsystem(GoalSubsystem):
    name = "run"
    help = softwrap(
        """
        Runs a binary target.

        This goal propagates the return code of the underlying executable.

        If your application can safely be restarted while it is running, you can pass
        `restartable=True` on your binary target (for supported types), and the `run` goal
        will automatically restart them as all relevant files change. This can be particularly
        useful for server applications.
        """
    )

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return RunFieldSet in union_membership

    args = ArgsListOption(
        example="val1 val2 --debug",
        tool_name="the executed target",
        passthrough=True,
    )
    cleanup = BoolOption(
        default=True,
        deprecation_start_version="2.15.0.dev1",
        removal_version="2.16.0.dev1",
        removal_hint="Use the global `keep_sandboxes` option instead.",
        help=softwrap(
            """
            Whether to clean up the temporary directory in which the binary is chrooted.
            Set this to false to retain the directory, e.g., for debugging.

            Note that setting the global --keep-sandboxes option may also conserve this directory,
            along with those of all other processes that Pants executes. This option is more
            selective and controls just the target binary's directory.
            """
        ),
    )
    # See also `test.py`'s same option
    debug_adapter = BoolOption(
        default=False,
        help=softwrap(
            """
            Run the interactive process using a Debug Adapter
            (https://microsoft.github.io/debug-adapter-protocol/) for the language if supported.

            The interactive process used will be immediately blocked waiting for a client before
            continuing.
            """
        ),
    )


class Run(Goal):
    subsystem_cls = RunSubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY


class RankedFieldSets(NamedTuple):
    primary: tuple[RunFieldSet, ...]
    secondary: tuple[RunFieldSet, ...]


def _partition(
    iterable: Iterable[_T], pred: Callable[[_T], bool]
) -> tuple[tuple[_T, ...], tuple[_T, ...]]:
    t1, t2 = tee(iterable)
    return tuple(filter(pred, t2)), tuple(filterfalse(pred, t1))


@rule_helper
async def _find_what_to_run(
    goal_description: str,
) -> tuple[RunFieldSet, Target]:
    targets_to_valid_field_sets = await Get(
        TargetRootsToFieldSets,
        TargetRootsToFieldSetsRequest(
            RunFieldSet,
            goal_description=goal_description,
            no_applicable_targets_behavior=NoApplicableTargetsBehavior.error,
        ),
    )

    primary_target: Target | None = None
    primary_target_rfs: RankedFieldSets | None = None

    for target, field_sets in targets_to_valid_field_sets.mapping.items():
        rfs = RankedFieldSets(
            *_partition(
                field_sets,
                lambda field_set: not any(
                    isinstance(field, SecondaryOwnerMixin)
                    for field in dataclasses.astuple(field_set)
                ),
            )
        )
        # In the case of multiple Targets/FieldSets, prefer the "primary" ones to the "secondary" ones.
        if (
            primary_target is None
            or primary_target_rfs is None  # impossible, but satisfies mypy
            or (rfs.primary and not primary_target_rfs.primary)
        ):
            primary_target = target
            primary_target_rfs = rfs
        elif (rfs.primary and primary_target_rfs.primary) or (
            rfs.secondary and primary_target_rfs.secondary
        ):
            raise TooManyTargetsException(
                targets_to_valid_field_sets.mapping, goal_description=goal_description
            )

    assert primary_target is not None
    assert primary_target_rfs is not None
    field_sets = primary_target_rfs.primary or primary_target_rfs.secondary
    if len(field_sets) > 1:
        raise AmbiguousImplementationsException(
            primary_target,
            primary_target_rfs.primary + primary_target_rfs.secondary,
            goal_description=goal_description,
        )

    return field_sets[0], primary_target


@goal_rule
async def run(
    run_subsystem: RunSubsystem,
    debug_adapter: DebugAdapterSubsystem,
    global_options: GlobalOptions,
    workspace: Workspace,
    build_root: BuildRoot,
    complete_env: CompleteEnvironmentVars,
) -> Run:
    field_set, target = await _find_what_to_run("the `run` goal")

    await _warn_on_non_local_environments((target,), "the `run` goal")

    request = await (
        Get(RunRequest, RunFieldSet, field_set)
        if not run_subsystem.debug_adapter
        else Get(RunDebugAdapterRequest, RunFieldSet, field_set)
    )
    restartable = target.get(RestartableField).value
    keep_sandboxes = (
        global_options.keep_sandboxes
        if run_subsystem.options.is_default("cleanup")
        else (KeepSandboxes.never if run_subsystem.cleanup else KeepSandboxes.always)
    )

    if run_subsystem.debug_adapter:
        logger.info(
            softwrap(
                f"""
                Launching debug adapter at '{debug_adapter.host}:{debug_adapter.port}',
                which will wait for a client connection...
                """
            )
        )

    result = await Effect(
        InteractiveProcessResult,
        InteractiveProcess(
            argv=(*request.args, *run_subsystem.args),
            env={**complete_env, **request.extra_env},
            input_digest=request.digest,
            run_in_workspace=True,
            restartable=restartable,
            keep_sandboxes=keep_sandboxes,
            immutable_input_digests=request.immutable_input_digests,
            append_only_caches=request.append_only_caches,
        ),
    )

    return Run(result.exit_code)


def rules():
    return collect_rules()
