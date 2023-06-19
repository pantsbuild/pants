# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import dataclasses
import logging
from abc import ABCMeta
from dataclasses import dataclass
from enum import Enum, unique
from itertools import chain
from typing import Iterable, Iterator

from pants.core.goals.package import PackageFieldSet
from pants.core.goals.publish import (
    PublishFieldSet,
    PublishPackages,
    PublishProcesses,
    PublishProcessesRequest,
)
from pants.engine.addresses import Address, Addresses
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.engine_aware import EngineAwareParameter, EngineAwareReturnType
from pants.engine.environment import EnvironmentName
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import FallibleProcessResult, InteractiveProcess, Process
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    CoarsenedTarget,
    CoarsenedTargets,
    FieldSet,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    NoApplicableTargetsBehavior,
    Target,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import union
from pants.util.logging import LogLevel
from pants.util.memo import memoized_property

logger = logging.getLogger(__name__)


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class DeployFieldSet(FieldSet, metaclass=ABCMeta):
    """The FieldSet type for the `deploy` goal.

    Union members may list any fields required to fulfill the instantiation of the `DeployProcess`
    result of the deploy rule.
    """


@dataclass(frozen=True)
class DeployProcess:
    """A process that when executed will have the side effect of deploying a target.

    To provide with the ability to deploy a given target, create a custom `DeployFieldSet` for
    that given target and implement a rule that returns `DeployProcess` for that custom field set:

    Example:

        @dataclass(frozen=True)
        class MyDeploymentFieldSet(DeployFieldSet):
            pass

        @rule
        async def my_deployment_process(field_set: MyDeploymentFieldSet) -> DeployProcess:
            # Create the underlying process that executes the deployment
            process = Process(...)
            return DeployProcess(
                name="my_deployment",
                process=InteractiveProcess.from_process(process)
            )

        def rules():
            return [
                *collect_rules(),
                UnionRule(DeployFieldSet, MyDeploymentFieldSet)
            ]

    Use the `publish_dependencies` field to provide with a list of targets that produce packages
    which need to be externally published before the deployment process is executed.
    """

    name: str
    process: InteractiveProcess | None
    publish_dependencies: tuple[Target, ...] = ()
    description: str | None = None


class DeploySubsystem(GoalSubsystem):
    name = "experimental-deploy"
    help = "Perform a deployment process."

    required_union_implementation = (DeployFieldSet,)


@dataclass(frozen=True)
class Deploy(Goal):
    subsystem_cls = DeploySubsystem
    environment_behavior = Goal.EnvironmentBehavior.LOCAL_ONLY  # TODO(#17129) — Migrate this.


@dataclass(frozen=True)
class _PublishProcessesForTargetRequest:
    target: Target


@rule
async def publish_process_for_target(
    request: _PublishProcessesForTargetRequest,
) -> PublishProcesses:
    package_field_sets, publish_field_sets = await MultiGet(
        Get(FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, [request.target])),
        Get(FieldSetsPerTarget, FieldSetsPerTargetRequest(PublishFieldSet, [request.target])),
    )

    return await Get(
        PublishProcesses,
        PublishProcessesRequest(
            package_field_sets=package_field_sets.field_sets,
            publish_field_sets=publish_field_sets.field_sets,
        ),
    )


async def _publish_processes_for_targets(targets: Iterable[Target]) -> PublishProcesses:
    processes_per_target = await MultiGet(
        Get(PublishProcesses, _PublishProcessesForTargetRequest(target)) for target in targets
    )

    return PublishProcesses(chain.from_iterable(processes_per_target))


@dataclass(frozen=True)
class _DeployTargetRequest(EngineAwareParameter):
    target: CoarsenedTarget
    dependent: Address | None = None

    def debug_hint(self) -> str:
        result = self.target.representative.address.spec
        if self.dependent:
            result += f" from {self.dependent}"
        return result


class _DeployTargetRequests(Collection[_DeployTargetRequest]):
    pass


@dataclass(frozen=True)
class _DeployTargetDependenciesRequest(EngineAwareParameter):
    target: CoarsenedTarget

    def debug_hint(self) -> str | None:
        return self.target.representative.address.spec


class _DeployStepAction(Enum):
    PUBLISH_PACKAGE = 0
    DEPLOYMENT = 1


@unique
class _DeployStepOutcome(Enum):
    SKIPPED = 0
    SUCCESS = 1
    FAILURE = 2
    FAILED_DEPENDENCIES = 3


@dataclass(frozen=True)
class _DeployStepResult(EngineAwareReturnType):
    exit_code: int
    action: _DeployStepAction
    outcome: _DeployStepOutcome

    names: tuple[str, ...] = ()
    description: str | None = dataclasses.field(default=None, compare=False)
    substeps: tuple[_DeployStepResult, ...] = ()

    @classmethod
    def from_publish_process_result(
        cls,
        result: FallibleProcessResult,
        publish: PublishPackages,
    ) -> _DeployStepResult:
        return _DeployStepResult(
            exit_code=result.exit_code,
            outcome=_DeployStepResult._determine_outcome(result),
            action=_DeployStepAction.PUBLISH_PACKAGE,
            names=publish.names,
            description=publish.description,
        )

    @classmethod
    def from_deploy_process_result(
        cls,
        result: FallibleProcessResult,
        deploy: DeployProcess,
        substeps: Iterable[_DeployStepResult] | None = None,
    ) -> _DeployStepResult:
        return _DeployStepResult(
            exit_code=result.exit_code,
            outcome=_DeployStepResult._determine_outcome(result),
            action=_DeployStepAction.DEPLOYMENT,
            names=(deploy.name,),
            description=deploy.description,
            substeps=tuple(substeps or []),
        )

    @classmethod
    def failed_dependencies(
        cls, deploy: DeployProcess, results: _DeployStepResults
    ) -> _DeployStepResult:
        assert results.exit_code != 0
        return _DeployStepResult(
            exit_code=results.exit_code,
            action=_DeployStepAction.DEPLOYMENT,
            outcome=_DeployStepOutcome.FAILED_DEPENDENCIES,
            names=(deploy.name,),
            description=deploy.description,
            substeps=results,
        )

    @staticmethod
    def _determine_outcome(result: FallibleProcessResult) -> _DeployStepOutcome:
        return _DeployStepOutcome.SUCCESS if result.exit_code == 0 else _DeployStepOutcome.FAILURE

    @classmethod
    def skipped(
        cls,
        *,
        action: _DeployStepAction,
        names: Iterable[str] | None = None,
        description: str | None = None,
        substeps: Iterable[_DeployStepResult] | None = None,
    ) -> _DeployStepResult:
        return _DeployStepResult(
            exit_code=0,
            outcome=_DeployStepOutcome.SKIPPED,
            action=action,
            names=tuple(names or []),
            description=description,
            substeps=tuple(substeps or []),
        )

    def level(self) -> LogLevel | None:
        return LogLevel.INFO if self.exit_code == 0 else LogLevel.ERROR

    def message(self) -> str | None:
        if self.output:
            return "\n".join(self.output)

        return None

    @memoized_property
    def output(self) -> tuple[str, ...]:
        if self.outcome == _DeployStepOutcome.SKIPPED:
            status = "skipped"
            if self.description:
                status += f" {self.description}"
        else:
            if self.outcome == _DeployStepOutcome.SUCCESS:
                status = (
                    "published" if self.action == _DeployStepAction.PUBLISH_PACKAGE else "deployed"
                )
                prep = "to"
            else:
                status = (
                    "failed"
                    if self.outcome == _DeployStepOutcome.FAILURE
                    else "failed dependencies"
                )
                prep = "for"

            if self.description:
                status += f" {prep} {self.description}"

        result = []
        for name in self.names:
            result.append(f"{name} {status}")

        return tuple(result)

    @property
    def closure(self) -> Iterator[_DeployStepResult]:
        for substep in self.substeps:
            yield from substep.closure

        yield self


class _DeployStepResults(Collection[_DeployStepResult]):
    @memoized_property
    def exit_code(self) -> int:
        if len(self) == 0:
            return 0

        return max(result.exit_code for result in self)

    @property
    def closure(self) -> Iterator[_DeployStepResult]:
        for result in self:
            yield from result.closure


@rule(desc="Publish package dependencies", level=LogLevel.DEBUG)
async def _run_publish_process(publish: PublishPackages) -> _DeployStepResult:
    if publish.process:
        # TODO cheating here, but only by invoking the underly process I can run this in a `@rule`
        result = await Get(FallibleProcessResult, Process, publish.process.process)
        return _DeployStepResult.from_publish_process_result(result, publish)

    return _DeployStepResult.skipped(
        action=_DeployStepAction.PUBLISH_PACKAGE,
        names=publish.names,
        description=publish.description,
    )


@rule(desc="Run deployment step", level=LogLevel.DEBUG)
async def _run_deploy_process(deploy: DeployProcess) -> _DeployStepResult:
    publish_results: Iterable[_DeployStepResult] = []
    if deploy.publish_dependencies:
        publish_processes = await _publish_processes_for_targets(deploy.publish_dependencies)
        publish_results = _DeployStepResults(
            await MultiGet(
                Get(_DeployStepResult, PublishPackages, process) for process in publish_processes
            )
        )

        if publish_results.exit_code != 0:
            return _DeployStepResult.failed_dependencies(deploy, publish_results)

    if deploy.process:
        # TODO cheating here, but only by invoking the underly process I can run this in a `@rule`
        result = await Get(FallibleProcessResult, Process, deploy.process.process)
        return _DeployStepResult.from_deploy_process_result(
            result,
            deploy,
            substeps=publish_results,
        )

    return _DeployStepResult.skipped(
        action=_DeployStepAction.DEPLOYMENT,
        names=(deploy.name,),
        description=deploy.description,
        substeps=publish_results,
    )


@rule(desc="Deploy target dependencies", level=LogLevel.DEBUG)
async def _deploy_target_dependencies(
    request: _DeployTargetDependenciesRequest,
) -> _DeployTargetRequests:
    def should_ignore(dep: CoarsenedTarget) -> bool:
        us = request.target.representative.address
        them = dep.representative.address
        return us == them

    return _DeployTargetRequests(
        [
            _DeployTargetRequest(dep, dependent=request.target.representative.address)
            for dep in request.target.dependencies
            if not should_ignore(dep)
        ]
    )


@rule
async def _deploy_targets(requests: _DeployTargetRequests) -> _DeployStepResults:
    result = await MultiGet(
        Get(_DeployStepResult, _DeployTargetRequest, request) for request in requests
    )
    return _DeployStepResults(result)


@rule(desc="Deploy target", level=LogLevel.DEBUG)
async def _deploy_coarsened_target(request: _DeployTargetRequest) -> _DeployStepResult:
    dependency_results = await Get(
        _DeployStepResults, _DeployTargetDependenciesRequest(request.target)
    )
    if dependency_results.exit_code != 0:
        return _DeployStepResult(
            exit_code=dependency_results.exit_code,
            action=_DeployStepAction.DEPLOYMENT,
            outcome=_DeployStepOutcome.FAILED_DEPENDENCIES,
            substeps=dependency_results,
        )

    field_sets_per_target = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(DeployFieldSet, request.target.members)
    )
    deploy_processes = await MultiGet(
        Get(DeployProcess, DeployFieldSet, field_set)
        for field_set in field_sets_per_target.field_sets
    )

    deploy_results = _DeployStepResults(
        await MultiGet(
            Get(_DeployStepResult, DeployProcess, process) for process in deploy_processes
        )
    )

    all_results = [*dependency_results, *deploy_results]
    if deploy_results.exit_code > 0:
        return _DeployStepResult(
            exit_code=deploy_results.exit_code,
            action=_DeployStepAction.DEPLOYMENT,
            outcome=_DeployStepOutcome.FAILURE,
            substeps=tuple(all_results),
        )

    return _DeployStepResult(
        exit_code=0,
        action=_DeployStepAction.DEPLOYMENT,
        outcome=_DeployStepOutcome.SUCCESS,
        substeps=tuple(all_results),
    )


@goal_rule
async def run_deploy(console: Console, deploy_subsystem: DeploySubsystem) -> Deploy:
    target_roots_to_deploy_field_sets = await Get(
        TargetRootsToFieldSets,
        TargetRootsToFieldSetsRequest(
            DeployFieldSet,
            goal_description=f"the `{deploy_subsystem.name}` goal",
            no_applicable_targets_behavior=NoApplicableTargetsBehavior.error,
        ),
    )

    if not target_roots_to_deploy_field_sets.targets:
        return Deploy(exit_code=0)

    coarsened_targets = await Get(
        CoarsenedTargets,
        Addresses([tgt.address for tgt in target_roots_to_deploy_field_sets.targets]),
    )
    results = _DeployStepResults(
        await MultiGet(
            Get(_DeployStepResult, _DeployTargetRequest(tgt)) for tgt in coarsened_targets
        )
    )

    outputs: list[str] = []
    for step in results.closure:
        if step.outcome == _DeployStepOutcome.SKIPPED:
            sigil = console.sigil_skipped()
        elif step.outcome == _DeployStepOutcome.SUCCESS:
            sigil = console.sigil_succeeded()
        else:
            sigil = console.sigil_failed()

        for out in step.output:
            outputs.append(f"{sigil} {out}")

    console.print_stderr("")
    if not outputs:
        sigil = console.sigil_skipped()
        console.print_stderr(f"{sigil} Nothing deployed.")

    for line in outputs:
        console.print_stderr(line)

    return Deploy(results.exit_code)


def rules():
    return collect_rules()
