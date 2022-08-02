# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from abc import ABCMeta
from dataclasses import dataclass
from typing import Iterable

from pants.core.goals.package import PackageFieldSet
from pants.core.goals.publish import PublishFieldSet, PublishProcesses, PublishProcessesRequest
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
from pants.engine.rules import Effect, Get, MultiGet, collect_rules, goal_rule, rule_helper
from pants.engine.target import (
    FieldSet,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    NoApplicableTargetsBehavior,
    Target,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import union
from pants.option.option_types import ArgsListOption

logger = logging.getLogger(__name__)


@union
@dataclass(frozen=True)
class DeployFieldSet(FieldSet, metaclass=ABCMeta):
    """The FieldSet type for the `deploy` goal.
    
    Union members may list any fields required to fulfill the instantiation of the
    `DeployProcess` result of the deploy rule.
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

    args = ArgsListOption(
        example="",
        passthrough=True,
        extra_help="Arguments to pass to the underlying tool.",
    )


@dataclass(frozen=True)
class Deploy(Goal):
    subsystem_cls = DeploySubsystem


@rule_helper
async def _find_publish_processes(targets: Iterable[Target]) -> PublishProcesses:
    package_field_sets, publish_field_sets = await MultiGet(
        Get(FieldSetsPerTarget, FieldSetsPerTargetRequest(PackageFieldSet, targets)),
        Get(FieldSetsPerTarget, FieldSetsPerTargetRequest(PublishFieldSet, targets)),
    )

    return await Get(
        PublishProcesses,
        PublishProcessesRequest(
            package_field_sets=package_field_sets.field_sets,
            publish_field_sets=publish_field_sets.field_sets,
        ),
    )


@rule_helper
async def _invoke_process(
    console: Console,
    process: InteractiveProcess | None,
    *,
    names: Iterable[str],
    success_status: str,
    description: str | None = None,
) -> tuple[int, tuple[str, ...]]:
    results = []

    if not process:
        sigil = console.sigil_skipped()
        status = "skipped"
        if description:
            status += f" {description}"
        for name in names:
            results.append(f"{sigil} {name} {status}.")
        return 0, tuple(results)

    logger.debug(f"Execute {process}")
    res = await Effect(InteractiveProcessResult, InteractiveProcess, process)
    if res.exit_code == 0:
        sigil = console.sigil_succeeded()
        status = success_status
        prep = "to"
    else:
        sigil = console.sigil_failed()
        status = "failed"
        prep = "for"

    if description:
        status += f" {prep} {description}"

    for name in names:
        results.append(f"{sigil} {name} {status}")

    return res.exit_code, tuple(results)


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

    deploy_processes = await MultiGet(
        Get(DeployProcess, DeployFieldSet, field_set)
        for field_set in target_roots_to_deploy_field_sets.field_sets
    )

    exit_code: int = 0
    results: list[str] = []
    published_targets: set[Target] = set()
    for deploy in deploy_processes:
        # If any of the deployment processes has common publish dependencies, we run the publish step only
        # once for those common dependencies
        publish_dependency_targets = [
            tgt for tgt in deploy.publish_dependencies if tgt not in published_targets
        ]
        publish_processes = await _find_publish_processes(publish_dependency_targets)

        if publish_processes:
            logger.info(f"Publishing dependencies for {deploy.name}.")

        # Publish all deployment dependencies first.
        publish_exit_code = 0
        for publish in publish_processes:
            ec, statuses = await _invoke_process(
                console,
                publish.process,
                names=publish.names,
                description=publish.description,
                success_status="published",
            )
            publish_exit_code = ec if ec != 0 else publish_exit_code
            results.extend(statuses)

        if publish_exit_code == 0:
            published_targets.update(publish_dependency_targets)
        else:
            # If we could not publish all dependencies of a deployment process we skip the deployment step and continue.
            logger.warning(
                f"Failed publishing deployment dependencies for {deploy.name}. Skipping deployment."
            )

            sigil = console.sigil_failed()
            status = "failed"
            if deploy.description:
                status += f" for {deploy.description}"
            results.append(f"{sigil} {deploy.name} {status}")

            exit_code = publish_exit_code
            continue

        # Invoke the deployment.
        ec, statuses = await _invoke_process(
            console,
            deploy.process,
            names=[deploy.name],
            success_status="deployed",
            description=deploy.description,
        )
        exit_code = ec if ec != 0 else exit_code
        results.extend(statuses)

    console.print_stderr("")
    if not results:
        sigil = console.sigil_skipped()
        console.print_stderr(f"{sigil} Nothing deployed.")

    for line in results:
        console.print_stderr(line)

    return Deploy(exit_code)


def rules():
    return collect_rules()
