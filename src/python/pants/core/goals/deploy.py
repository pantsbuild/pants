# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import asyncio
import logging
from abc import ABCMeta
from collections import defaultdict, deque
from dataclasses import dataclass
from itertools import chain
from typing import Iterable, Iterator, Set, Tuple

from pants.core.goals.package import PackageFieldSet
from pants.core.goals.publish import PublishFieldSet, PublishProcesses, PublishProcessesRequest
from pants.engine.addresses import Address, Addresses
from pants.engine.console import Console
from pants.engine.environment import EnvironmentName
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
from pants.engine.rules import Effect, Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    Dependencies,
    DependenciesRequest,
    FieldSet,
    FieldSetsPerTarget,
    FieldSetsPerTargetRequest,
    NoApplicableTargetsBehavior,
    Target,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.engine.unions import union
from pants.util.frozendict import FrozenDict
from pants.util.ordered_set import OrderedSet

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
class _FallibleProcResult:
    exit_code: int
    outputs: tuple[str, ...]


async def _invoke_process(
    console: Console,
    process: InteractiveProcess | None,
    *,
    names: Iterable[str],
    success_status: str,
    description: str | None = None,
) -> _FallibleProcResult:
    outputs = []

    if not process:
        sigil = console.sigil_skipped()
        status = "skipped"
        if description:
            status += f" {description}"
        for name in names:
            outputs.append(f"{sigil} {name} {status}.")
        return _FallibleProcResult(0, tuple(outputs))

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
        outputs.append(f"{sigil} {name} {status}")

    return _FallibleProcResult(res.exit_code, tuple(outputs))


@dataclass(frozen=True)
class _DeployGraphNode:
    target: Target
    field_set: DeployFieldSet
    process: DeployProcess

    @property
    def address(self) -> Address:
        return self.field_set.address


@dataclass(frozen=True)
class _DeployStep:
    nodes: tuple[_DeployGraphNode, ...]


@dataclass(frozen=True)
class _DeployGraph:
    dependents: FrozenDict[Address, Tuple[_DeployGraphNode, ...]]
    roots: Tuple[_DeployGraphNode, ...]

    @property
    def steps(self) -> Iterator[_DeployStep]:
        visited = set()
        queue = deque([self.roots])
        while queue:
            nodes = queue.popleft()
            non_visitied = {node for node in nodes if node.address not in visited}
            if not non_visitied:
                continue

            visited.update([node.address for node in non_visitied])
            yield _DeployStep(tuple(non_visitied))

            next_nodes: Set[_DeployGraphNode] = set()
            for node in non_visitied:
                next_nodes.update(self.dependents.get(node.address, ()))
            queue.extend([tuple(next_nodes)])

    @property
    def publish_dependencies(self) -> set[Target]:
        return {
            tgt
            for step in self.steps
            for node in step.nodes
            for tgt in node.process.publish_dependencies
        }


async def _build_deploy_graph(addresses: Iterable[Address]) -> _DeployGraph:
    mapping: dict[Address, set[_DeployGraphNode]] = defaultdict(set)
    transitive_targets = await Get(TransitiveTargets, TransitiveTargetsRequest(addresses))
    field_sets_per_target = await Get(
        FieldSetsPerTarget, FieldSetsPerTargetRequest(DeployFieldSet, transitive_targets.closure)
    )

    deployable_targets = [
        (tgt, field_sets[0])
        for tgt, field_sets in zip(transitive_targets.closure, field_sets_per_target.collection)
        if field_sets
    ]
    deploy_procs = await MultiGet(
        Get(DeployProcess, DeployFieldSet, field_set) for _, field_set in deployable_targets
    )
    graph_nodes = [
        _DeployGraphNode(tgt, fs, proc) for (tgt, fs), proc in zip(deployable_targets, deploy_procs)
    ]

    dependencies_per_target = await MultiGet(
        Get(Addresses, DependenciesRequest(node.target.get(Dependencies))) for node in graph_nodes
    )

    roots: OrderedSet[_DeployGraphNode] = OrderedSet()
    for node, dependencies in zip(graph_nodes, dependencies_per_target):
        if not dependencies:
            # The roots of the graph are those who have no dependencies
            roots.add(node)
            continue

        for dependency in dependencies:
            mapping[dependency].add(node)

    return _DeployGraph(
        roots=tuple(roots),
        dependents=FrozenDict({addr: tuple(nodes) for addr, nodes in mapping.items()}),
    )


async def _publish_packages(targets: Iterable[Target], console: Console) -> _FallibleProcResult:
    publish_processes = await _publish_processes_for_targets(targets)
    proc_results = await asyncio.gather(
        *[
            _invoke_process(
                console,
                publish.process,
                names=publish.names,
                description=publish.description,
                success_status="published",
            )
            for publish in publish_processes
        ]
    )

    exit_code = max(result.exit_code for result in proc_results)
    outputs = chain.from_iterable([result.outputs for result in proc_results])
    return _FallibleProcResult(exit_code, tuple(outputs))


async def _run_deploy_step(step: _DeployStep, console: Console) -> _FallibleProcResult:
    proc_results = await asyncio.gather(
        *[
            _invoke_process(
                console,
                node.process.process,
                names=[node.process.name],
                description=node.process.description,
                success_status="deployed",
            )
            for node in step.nodes
        ]
    )

    exit_code = max(result.exit_code for result in proc_results)
    outputs = chain.from_iterable([result.outputs for result in proc_results])
    return _FallibleProcResult(exit_code, tuple(outputs))


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

    deployment_graph = await _build_deploy_graph(
        [tgt.address for tgt in target_roots_to_deploy_field_sets.targets]
    )

    exit_code = 0
    outputs: list[str] = []

    publish_dependencies = deployment_graph.publish_dependencies
    if publish_dependencies:
        result = await _publish_packages(publish_dependencies, console)
        exit_code = result.exit_code
        outputs = list(result.outputs)

    for step in deployment_graph.steps:
        if exit_code != 0:
            break

        deploy_result = await _run_deploy_step(step, console)
        exit_code = deploy_result.exit_code
        outputs.extend(deploy_result.outputs)

    console.print_stderr("")
    if not outputs:
        sigil = console.sigil_skipped()
        console.print_stderr(f"{sigil} Nothing deployed.")

    for line in outputs:
        console.print_stderr(line)

    return Deploy(exit_code)


def rules():
    return collect_rules()
