# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from abc import ABCMeta
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Iterable, Mapping, Optional, Tuple, TypeVar, Union

from typing_extensions import final

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
from pants.engine.rules import Effect, Get, Rule, _uncacheable_rule, collect_rules, goal_rule, rule
from pants.engine.target import (
    BoolField,
    FieldSet,
    NoApplicableTargetsBehavior,
    Target,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.option.global_options import GlobalOptions
from pants.option.option_types import ArgsListOption, BoolOption
from pants.util.frozendict import FrozenDict
from pants.util.memo import memoized
from pants.util.strutil import help_text, softwrap

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


class RunInSandboxBehavior(Enum):
    """Defines the behavhior of rules that act on a `RunFieldSet` subclass with regards to use in
    the sandbox.

    This is used to automatically generate rules used to fulfill `experimental_run_in_sandbox`
    targets.

    The behaviors are as follows:

    * `RUN_REQUEST_HERMETIC`: Use the existing `RunRequest`-generating rule, and enable cacheing.
       Use this if you are confident the behaviour of the rule relies only on state that is
       captured by pants (e.g. binary paths are found using `EnvironmentVarsRequest`), and that
       the rule only refers to files in the sandbox.
    * `RUN_REQUEST_NOT_HERMETIC`: Use the existing `RunRequest`-generating rule, and do not
       enable cacheing. Use this if your existing rule is mostly suitable for use in the sandbox,
       but you cannot guarantee reproducible behavior.
    * `CUSTOM`: Opt to write your own rule that returns `RunInSandboxRequest`.
    * `NOT_SUPPORTED`: Opt out of being usable in `experimental_run_in_sandbox`. Attempting to use
       such a target will result in a runtime exception.
    """

    RUN_REQUEST_HERMETIC = 1
    RUN_REQUEST_NOT_HERMETIC = 2
    CUSTOM = 3
    NOT_SUPPORTED = 4


@union(in_scope_types=[EnvironmentName])
class RunFieldSet(FieldSet, metaclass=ABCMeta):
    """The fields necessary from a target to run a program/script."""

    supports_debug_adapter: ClassVar[bool] = False
    run_in_sandbox_behavior: ClassVar[RunInSandboxBehavior]

    @final
    @classmethod
    def rules(cls) -> Iterable[Union[Rule, UnionRule]]:
        yield UnionRule(RunFieldSet, cls)
        if not cls.supports_debug_adapter:
            yield from _unsupported_debug_adapter_rules(cls)
        yield from _run_in_sandbox_behavior_rule(cls)


class RestartableField(BoolField):
    alias = "restartable"
    default = False
    help = help_text(
        """
        If true, runs of this target with the `run` goal may be interrupted and
        restarted when its input files change.
        """
    )


@dataclass(frozen=True)
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
        object.__setattr__(self, "digest", digest)
        object.__setattr__(self, "args", tuple(args))
        object.__setattr__(self, "extra_env", FrozenDict(extra_env or {}))
        object.__setattr__(
            self, "immutable_input_digests", FrozenDict(immutable_input_digests or {})
        )
        object.__setattr__(self, "append_only_caches", FrozenDict(append_only_caches or {}))

    def to_run_in_sandbox_request(self) -> RunInSandboxRequest:
        return RunInSandboxRequest(
            args=self.args,
            digest=self.digest,
            extra_env=self.extra_env,
            immutable_input_digests=self.immutable_input_digests,
            append_only_caches=self.append_only_caches,
        )


class RunDebugAdapterRequest(RunRequest):
    """Like RunRequest, but launches the process using the relevant Debug Adapter server.

    The process should be launched waiting for the client to connect.
    """


class RunInSandboxRequest(RunRequest):
    """A run request that launches the process in the sandbox for use as part of a build rule.

    The arguments and environment should only use values relative to the build root (or prefixed
    with `{chroot}`), or refer to binaries that were fetched with `BinaryPathRequest`.

    Presently, implementors can opt to use the existing as not guaranteeing hermeticity, which will
    internally mark the rule as uncacheable. In such a case, non-safe APIs can be used, however,
    this behavior can result in poorer performance, and only exists as a stop-gap while
    implementors work to make sure their `RunRequest`-generating rules can be used in a hermetic
    context, or writing new custom rules. (See the Plugin Upgrade Guide for details).
    """


class RunSubsystem(GoalSubsystem):
    name = "run"
    help = help_text(
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
    mapping = targets_to_valid_field_sets.mapping

    if len(mapping) > 1:
        raise TooManyTargetsException(mapping, goal_description=goal_description)

    target, field_sets = next(iter(mapping.items()))
    if len(field_sets) > 1:
        raise AmbiguousImplementationsException(
            target,
            field_sets,
            goal_description=goal_description,
        )

    return field_sets[0], target


@goal_rule
async def run(
    run_subsystem: RunSubsystem,
    debug_adapter: DebugAdapterSubsystem,
    global_options: GlobalOptions,
    workspace: Workspace,  # Needed to enable sideeffecting.
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
            keep_sandboxes=global_options.keep_sandboxes,
            immutable_input_digests=request.immutable_input_digests,
            append_only_caches=request.append_only_caches,
        ),
    )

    return Run(result.exit_code)


@memoized
def _unsupported_debug_adapter_rules(cls: type[RunFieldSet]) -> Iterable:
    """Returns a rule that implements DebugAdapterRequest by raising an error."""

    @rule(canonical_name_suffix=cls.__name__, _param_type_overrides={"request": cls})
    async def get_run_debug_adapter_request(request: RunFieldSet) -> RunDebugAdapterRequest:
        raise NotImplementedError(
            "Running this target type with a debug adapter is not yet supported."
        )

    return collect_rules(locals())


async def _run_request(request: RunFieldSet) -> RunInSandboxRequest:
    run_request = await Get(RunRequest, RunFieldSet, request)
    return run_request.to_run_in_sandbox_request()


@memoized
def _run_in_sandbox_behavior_rule(cls: type[RunFieldSet]) -> Iterable:
    """Returns a default rule that helps fulfil `experimental_run_in_sandbox` targets.

    If `RunInSandboxBehavior.CUSTOM` is specified, rule implementors must write a rule that returns
    a `RunInSandboxRequest`.
    """

    @rule(canonical_name_suffix=cls.__name__, _param_type_overrides={"request": cls})
    async def not_supported(request: RunFieldSet) -> RunInSandboxRequest:
        raise NotImplementedError(
            "Running this target type within the sandbox is not yet supported."
        )

    @rule(canonical_name_suffix=cls.__name__, _param_type_overrides={"request": cls})
    async def run_request_hermetic(request: RunFieldSet) -> RunInSandboxRequest:
        return await _run_request(request)

    @_uncacheable_rule(canonical_name_suffix=cls.__name__, _param_type_overrides={"request": cls})
    async def run_request_not_hermetic(request: RunFieldSet) -> RunInSandboxRequest:
        return await _run_request(request)

    default_rules = {
        RunInSandboxBehavior.NOT_SUPPORTED: [not_supported],
        RunInSandboxBehavior.RUN_REQUEST_HERMETIC: [run_request_hermetic],
        RunInSandboxBehavior.RUN_REQUEST_NOT_HERMETIC: [run_request_not_hermetic],
        RunInSandboxBehavior.CUSTOM: [],
    }

    return collect_rules(
        {_rule.__name__: _rule for _rule in default_rules[cls.run_in_sandbox_behavior]}
    )


def rules():
    return collect_rules()
