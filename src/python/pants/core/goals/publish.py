# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Goal for publishing packaged targets to any repository or registry etc.

Plugins implement the publish protocol that provides this goal with the processes to run in order to
publish the artifacts.

The publish protocol consists of defining two union members and one rule, returning the processes to
run. See the doc for the corresponding classses in this module for details on the classes to define.

Example rule:

    @rule
    async def publish_example(request: PublishToMyRepoRequest, ...) -> PublishProcesses:
      # Create `InteractiveProcess` instances as required by the `request`.
      return PublishProcesses(...)
"""


from __future__ import annotations

import logging
from abc import ABCMeta
from dataclasses import dataclass
from itertools import chain
from typing import ClassVar, Generic, Type, TypeVar

from typing_extensions import final

from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.process import InteractiveProcess, InteractiveProcessResult
from pants.engine.rules import Effect, Get, MultiGet, collect_rules, goal_rule, rule
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
class PublishRequest(Generic[_F]):
    """Implement a union member subclass of this union class along with a PublishFieldSet subclass
    that appoints that member subclass in order to receive publish requests for targets compatible
    with the field set.

    The `packages` hold all artifacts produced for a given target to be published.

    Example:

        PublishToMyRepoRequest(PublishRequest):
          pass

        PublishToMyRepoFieldSet(PublishFieldSet):
          publish_request_type = PublishToMyRepoRequest

          # Standard FieldSet semantics from here on:
          required_fields = (MyRepositories,)
          ...
    """

    field_set: _F
    packages: tuple[BuiltPackage, ...]


_T = TypeVar("_T", bound=PublishRequest)


@union
@dataclass(frozen=True)
class PublishFieldSet(Generic[_T], FieldSet, metaclass=ABCMeta):
    """FieldSet for PublishRequest.

    Union members may list any fields required to fullfill the instantiation of the
    `PublishProcesses` result of the publish rule.
    """

    # Subclasses must provide this, to a union member (subclass) of `PublishRequest`.
    publish_request_type: ClassVar[Type[_T]]

    @final
    def _request(self, packages: tuple[BuiltPackage, ...]) -> _T:
        """Internal helper for the core publish goal."""
        return self.publish_request_type(field_set=self, packages=packages)

    @final
    @classmethod
    def rules(cls) -> tuple[UnionRule, ...]:
        """Helper method for registering the union members."""
        return (
            UnionRule(PublishFieldSet, cls),
            UnionRule(PublishRequest, cls.publish_request_type),
        )


@dataclass(frozen=True)
class PublishPackages:
    """Processes to run in order to publish the named artifacts.

    The `names` should list all artifacts being published by the `process` command.

    The `process` may be `None`, indicating that it will not be published. This will be logged as
    `skipped`. If the process returns a non zero exit code, it will be logged as `failed`.

    The `description` may be a reason explaining why the publish was skipped, or identifying which
    repository the artifacts are published to.
    """

    names: tuple[str, ...]
    process: InteractiveProcess | None = None
    description: str | None = None


class PublishProcesses(Collection[PublishPackages]):
    """Collection of what processes to run for all built packages.

    This is returned from implementing rules in response to a PublishRequest.

    Depending on the capabilities of the publishing tool, the work may be partitioned based on
    number of artifacts and/or repositories to publish to.
    """


@dataclass(frozen=True)
class PublishProcessesRequest:
    """Internal request taking all field sets for a target and turning it into a `PublishProcesses`
    collection (via registered publish plugins)."""

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
async def run_publish(console: Console) -> Publish:
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
    processes = await MultiGet(
        Get(
            PublishProcesses,
            PublishProcessesRequest(
                target_roots_to_package_field_sets.mapping[tgt],
                target_roots_to_publish_field_sets.mapping[tgt],
            ),
        )
        for tgt in targets
    )

    # Run all processes interactively.
    exit_code = 0
    results = []
    for pub in chain.from_iterable(processes):
        if not pub.process:
            sigil = console.sigil_skipped()
            status = "skipped"
            if pub.description:
                status += f" {pub.description}"
            for name in pub.names:
                results.append(f"{sigil} {name} {status}.")
            continue

        res = await Effect(InteractiveProcessResult, InteractiveProcess, pub.process)
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
            results.append(f"{sigil} {name} {status}.")

    console.print_stderr("")
    if not results:
        sigil = console.sigil_skipped()
        console.print_stderr(f"{sigil} Nothing published.")

    # We collect all results to the end, so all output from the interactive processes are done,
    # before printing the results.
    for line in results:
        console.print_stderr(line)

    return Publish(exit_code)


@rule
async def package_for_publish(request: PublishProcessesRequest) -> PublishProcesses:
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
            PublishProcesses,
            PublishRequest,
            field_set._request(packages),
        )
        for field_set in request.publish_field_sets
    )

    # Merge all PublishProcesses into one.
    return PublishProcesses(chain.from_iterable(publish))


def rules():
    return collect_rules()
