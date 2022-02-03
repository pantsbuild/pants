# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
import logging
from abc import ABCMeta
from dataclasses import dataclass
from pathlib import PurePath
from typing import Iterable, Mapping, Optional, Tuple, cast

from pants.base.build_root import BuildRoot
from pants.build_graph.address import Address
from pants.engine.environment import CompleteEnvironment
from pants.engine.fs import Digest, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
from pants.engine.rules import Effect, Get, collect_rules, goal_rule
from pants.engine.target import (
    BoolField,
    FieldSet,
    NoApplicableTargetsBehavior,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
    WrappedTarget,
)
from pants.engine.unions import union
from pants.option.custom_types import shell_str
from pants.option.global_options import GlobalOptions
from pants.util.contextutil import temporary_dir
from pants.util.frozendict import FrozenDict
from pants.util.meta import frozen_after_init

logger = logging.getLogger(__name__)


@union
class RunFieldSet(FieldSet, metaclass=ABCMeta):
    """The fields necessary from a target to run a program/script."""


class RestartableField(BoolField):
    alias = "restartable"
    default = False
    help = (
        "If true, runs of this target with the `run` goal may be interrupted and "
        "restarted when its input files change."
    )


@frozen_after_init
@dataclass(unsafe_hash=True)
class RunRequest:
    digest: Digest
    # Values in args and in env can contain the format specifier "{chroot}", which will
    # be substituted with the (absolute) chroot path.
    args: Tuple[str, ...]
    extra_env: FrozenDict[str, str]

    def __init__(
        self,
        *,
        digest: Digest,
        args: Iterable[str],
        extra_env: Optional[Mapping[str, str]] = None,
    ) -> None:
        self.digest = digest
        self.args = tuple(args)
        self.extra_env = FrozenDict(extra_env or {})


class RunSubsystem(GoalSubsystem):
    name = "run"
    help = (
        "Runs a binary target.\n\n"
        "This goal propagates the return code of the underlying executable.\n\n"
        "If your application can safely be restarted while it is running, you can pass "
        "`restartable=True` on your binary target (for supported types), and the `run` goal "
        "will automatically restart them as all relevant files change. This can be particularly "
        "useful for server applications."
    )

    required_union_implementations = (RunFieldSet,)

    @classmethod
    def register_options(cls, register) -> None:
        super().register_options(register)
        register(
            "--args",
            type=list,
            member_type=shell_str,
            passthrough=True,
            help="Arguments to pass directly to the executed target, e.g. "
            '`--run-args="val1 val2 --debug"`',
        )
        register(
            "--cleanup",
            type=bool,
            default=True,
            help="Whether to clean up the temporary directory in which the binary is chrooted. "
            "Set to false to retain the directory, e.g., for debugging.",
        )

    @property
    def args(self) -> Tuple[str, ...]:
        return tuple(self.options.args)

    @property
    def cleanup(self) -> bool:
        return cast(bool, self.options.cleanup)


class Run(Goal):
    subsystem_cls = RunSubsystem


@goal_rule
async def run(
    run_subsystem: RunSubsystem,
    global_options: GlobalOptions,
    workspace: Workspace,
    build_root: BuildRoot,
    complete_env: CompleteEnvironment,
) -> Run:
    targets_to_valid_field_sets = await Get(
        TargetRootsToFieldSets,
        TargetRootsToFieldSetsRequest(
            RunFieldSet,
            goal_description="the `run` goal",
            no_applicable_targets_behavior=NoApplicableTargetsBehavior.error,
            expect_single_field_set=True,
        ),
    )
    field_set = targets_to_valid_field_sets.field_sets[0]
    request = await Get(RunRequest, RunFieldSet, field_set)
    wrapped_target = await Get(WrappedTarget, Address, field_set.address)
    restartable = wrapped_target.target.get(RestartableField).value

    with temporary_dir(
        root_dir=global_options.options.pants_workdir, cleanup=run_subsystem.cleanup
    ) as tmpdir:
        if not run_subsystem.cleanup:
            logger.info(f"Preserving running binary chroot {tmpdir}")
        workspace.write_digest(
            request.digest,
            path_prefix=PurePath(tmpdir).relative_to(build_root.path).as_posix(),
            # We don't want to influence whether the InteractiveProcess is able to restart. Because
            # we're writing into a temp directory, we can safely mark this side_effecting=False.
            side_effecting=False,
        )

        args = (arg.format(chroot=tmpdir) for arg in request.args)
        env = {**complete_env, **{k: v.format(chroot=tmpdir) for k, v in request.extra_env.items()}}
        result = await Effect(
            InteractiveProcessResult,
            InteractiveProcess(
                argv=(*args, *run_subsystem.args),
                env=env,
                run_in_workspace=True,
                restartable=restartable,
            ),
        )
        exit_code = result.exit_code

    return Run(exit_code)


def rules():
    return collect_rules()
