# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from abc import ABCMeta
from dataclasses import dataclass
from itertools import chain
from typing import ClassVar, Generic, Iterable, Type, TypeVar

from typing_extensions import final

from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import InteractiveProcess, InteractiveRunner
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    FieldSet,
    NoApplicableTargetsBehavior,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import UnionRule, union

logger = logging.getLogger(__name__)


_F = TypeVar("_F", bound=FieldSet)


@union
@dataclass(frozen=True)
class PublishPackagesRequest(Generic[_F]):
    field_set: _F
    packages: tuple[BuiltPackage, ...]


_T = TypeVar("_T", bound=PublishPackagesRequest)


@union
@dataclass(frozen=True)
class PublishFieldSet(Generic[_T], FieldSet, metaclass=ABCMeta):
    """The fields necessary to publish an asset from a target.

    Implementing rules should subclass this class ... and return a PublishPackageArtifactRequest as
    output.
    """

    publish_request_type: ClassVar[Type[_T]]

    @final
    def request(self, packages: tuple[BuiltPackage, ...]) -> _T:
        return self.publish_request_type(field_set=self, packages=packages)

    @final
    @classmethod
    def rules(cls) -> tuple[UnionRule, ...]:
        return (
            UnionRule(PublishFieldSet, cls),
            UnionRule(PublishPackagesRequest, cls.publish_request_type),
        )


@dataclass(frozen=True)
class PublishPackageProcesses:
    """Process to run in order to publish named artifact.

    There are multiple names to support processes working on several packages for each process.
    There are multiple processes to support publishing to several upstream services for each
    package.
    """

    names: tuple[str, ...]
    processes: tuple[InteractiveProcess, ...] = ()
    description: str | None = None


@dataclass(frozen=True)
class PublishPackagesProcesses:
    """Collection of what processes to run for all built artifacts.

    This is returned from implementing rules in response to a PublishPackagesRequest.
    """

    packages: tuple[PublishPackageProcesses, ...]


@dataclass(frozen=True)
class PublishPackagesProcessesRequest:
    package_field_sets: tuple[PackageFieldSet, ...]
    publish_field_sets: tuple[PublishFieldSet, ...]


class PublishSubsystem(GoalSubsystem):
    name = "publish"
    help = "Publish deliverables (assets, distributions, images, etc)."

    required_union_implementations = (
        PackageFieldSet,
        PublishFieldSet,
    )


class Publish(Goal):
    subsystem_cls = PublishSubsystem


@goal_rule
async def run_publish(console: Console, interactive_runner: InteractiveRunner) -> Publish:
    target_roots_to_package_field_sets, target_roots_to_publish_field_sets = await MultiGet(
        Get(
            TargetRootsToFieldSets,
            TargetRootsToFieldSetsRequest(
                field_set,
                goal_description="the `publish` goal",
                no_applicable_targets_behavior=NoApplicableTargetsBehavior.warn,
            ),
        )
        for field_set in [PackageFieldSet, PublishFieldSet]
    )

    # Only keep field sets that both package someething, and have something to publish.
    targets = set(target_roots_to_package_field_sets.targets).intersection(
        set(target_roots_to_publish_field_sets.targets)
    )

    if not targets:
        return Publish(exit_code=0)

    # Build all packages and request the processes to run for each field set.
    work = await MultiGet(
        Get(
            PublishPackagesProcesses,
            PublishPackagesProcessesRequest(
                target_roots_to_package_field_sets.mapping[tgt],
                target_roots_to_publish_field_sets.mapping[tgt],
            ),
        )
        for tgt in targets
    )

    # Run all processes interactively.
    exit_code, results = run_publish_processes(
        console, interactive_runner, chain.from_iterable(wrk.packages for wrk in work)
    )

    console.print_stderr("")
    if not results:
        sigil = console.sigil_skipped()
        console.print_stderr(f"{sigil} Nothing published.")

    # We collect all results to the end, so all output from the interactive processes are done,
    # before printing the results.
    for line in results:
        console.print_stderr(line)

    return Publish(exit_code)


def run_publish_processes(
    console: Console,
    interactive_runner: InteractiveRunner,
    publish_processes: Iterable[PublishPackageProcesses],
) -> tuple[int, list[str]]:
    exit_code = 0
    output = []
    for pub in publish_processes:
        if not pub.processes:
            sigil = console.sigil_skipped()
            status = "skipped"
            if pub.description:
                status += f" {pub.description}"
            for name in pub.names:
                output.append(f"{sigil} {name} {status}.")
            continue

        for res in (interactive_runner.run(proc) for proc in pub.processes):
            if res.exit_code == 0:
                sigil = console.sigil_succeeded()
                status = "published"
                prep = "to"
            else:
                sigil = console.sigil_failed()
                status = "failed"
                prep = "for"
                exit_code = res.exit_code

            if pub.description:
                status += f" {prep} {pub.description}"

            for name in pub.names:
                output.append(f"{sigil} {name} {status}.")
    return exit_code, output


@rule
async def package_for_publish(request: PublishPackagesProcessesRequest) -> PublishPackagesProcesses:
    packages = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, field_set) for field_set in request.package_field_sets
    )

    for pkg in packages:
        for artifact in pkg.artifacts:
            if artifact.relpath:
                logger.info(f"Packaged {artifact.relpath}")
            elif artifact.extra_log_lines:
                logger.info(str(artifact.extra_log_lines[0]))

    publish = await MultiGet(
        Get(
            PublishPackagesProcesses,
            PublishPackagesRequest,
            field_set.request(packages),
        )
        for field_set in request.publish_field_sets
    )

    # Merge all PublishPackagesProcesses into one.
    return PublishPackagesProcesses(tuple(chain.from_iterable(pub.packages for pub in publish)))


def rules():
    return collect_rules()
