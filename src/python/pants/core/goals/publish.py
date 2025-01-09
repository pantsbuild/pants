# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
"""Goal for publishing packaged targets to any repository or registry etc.

Plugins implement the publish protocol that provides this goal with the processes to run in order to
publish the artifacts.

The publish protocol consists of defining two union members and one rule, returning the processes to
run. See the doc for the corresponding classes in this module for details on the classes to define.

Example rule:

    @rule
    async def publish_example(request: PublishToMyRepoRequest, ...) -> PublishProcesses:
      # Create `InteractiveProcess` instances as required by the `request`.
      return PublishProcesses(...)
"""


from __future__ import annotations

import collections
import json
import logging
from abc import ABCMeta
from dataclasses import asdict, dataclass, field, is_dataclass, replace
from itertools import chain
from typing import ClassVar, Generic, Type, TypeVar

from typing_extensions import final

from pants.core.goals.package import BuiltPackage, EnvironmentAwarePackageRequest, PackageFieldSet
from pants.engine.addresses import Address
from pants.engine.collection import Collection
from pants.engine.console import Console
from pants.engine.environment import ChosenLocalEnvironmentName, EnvironmentName
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.intrinsics import run_interactive_process_in_environment
from pants.engine.process import InteractiveProcess
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule, rule
from pants.engine.target import (
    FieldSet,
    ImmutableValue,
    NoApplicableTargetsBehavior,
    TargetRootsToFieldSets,
    TargetRootsToFieldSetsRequest,
)
from pants.engine.unions import UnionMembership, UnionRule, union
from pants.option.option_types import StrOption
from pants.util.frozendict import FrozenDict

logger = logging.getLogger(__name__)


_F = TypeVar("_F", bound=FieldSet)


class PublishOutputData(FrozenDict[str, ImmutableValue]):
    pass


@union(in_scope_types=[EnvironmentName])
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


@union(in_scope_types=[EnvironmentName])
@dataclass(frozen=True)
class PublishFieldSet(Generic[_T], FieldSet, metaclass=ABCMeta):
    """FieldSet for PublishRequest.

    Union members may list any fields required to fulfill the instantiation of the
    `PublishProcesses` result of the publish rule.
    """

    # Subclasses must provide this, to a union member (subclass) of `PublishRequest`.
    publish_request_type: ClassVar[Type[_T]]  # type: ignore[misc]

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

    def get_output_data(self) -> PublishOutputData:
        return PublishOutputData({"target": self.address})


@dataclass(frozen=True)
class PublishPackages:
    """Processes to run in order to publish the named artifacts.

    The `names` should list all artifacts being published by the `process` command.

    The `process` may be `None`, indicating that it will not be published. This will be logged as
    `skipped`. If the process returns a non-zero exit code, it will be logged as `failed`.

    The `description` may be a reason explaining why the publish was skipped, or identifying which
    repository the artifacts are published to.
    """

    names: tuple[str, ...]
    process: InteractiveProcess | None = None
    description: str | None = None
    data: PublishOutputData = field(default_factory=PublishOutputData)

    def get_output_data(self, **extra_data) -> PublishOutputData:
        return PublishOutputData(
            {
                "names": self.names,
                **self.data,
                **extra_data,
            }
        )


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

    @classmethod
    def activated(cls, union_membership: UnionMembership) -> bool:
        return PackageFieldSet in union_membership and PublishFieldSet in union_membership

    output = StrOption(
        default=None,
        help="Filename for JSON structured publish information.",
    )


class Publish(Goal):
    subsystem_cls = PublishSubsystem
    environment_behavior = Goal.EnvironmentBehavior.USES_ENVIRONMENTS


@goal_rule
async def run_publish(
    console: Console, publish: PublishSubsystem, local_environment: ChosenLocalEnvironmentName
) -> Publish:
    target_roots_to_package_field_sets, target_roots_to_publish_field_sets = await MultiGet(
        Get(
            TargetRootsToFieldSets,
            TargetRootsToFieldSetsRequest(
                PackageFieldSet,
                goal_description="",
                # Don't warn/error here because it's already covered by `PublishFieldSet`.
                no_applicable_targets_behavior=NoApplicableTargetsBehavior.ignore,
            ),
        ),
        Get(
            TargetRootsToFieldSets,
            TargetRootsToFieldSetsRequest(
                PublishFieldSet,
                goal_description="the `publish` goal",
                no_applicable_targets_behavior=NoApplicableTargetsBehavior.warn,
            ),
        ),
    )

    # Only keep field sets that both package something, and have something to publish.
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
    exit_code: int = 0
    outputs: list[PublishOutputData] = []
    results: list[str] = []

    for pub in chain.from_iterable(processes):
        if not pub.process:
            sigil = console.sigil_skipped()
            status = "skipped"
            if pub.description:
                status += f" {pub.description}"
            for name in pub.names:
                results.append(f"{sigil} {name} {status}.")
            outputs.append(pub.get_output_data(published=False, status=status))
            continue

        logger.debug(f"Execute {pub.process}")
        res = await run_interactive_process_in_environment(pub.process, local_environment.val)
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

        outputs.append(
            pub.get_output_data(
                exit_code=res.exit_code,
                published=res.exit_code == 0,
                status=status,
            )
        )

    console.print_stderr("")
    if not results:
        sigil = console.sigil_skipped()
        console.print_stderr(f"{sigil} Nothing published.")

    # We collect all results to the end, so all output from the interactive processes are done,
    # before printing the results.
    for line in sorted(results):
        console.print_stderr(line)

    # Log structured output
    output_data = json.dumps(outputs, cls=_PublishJsonEncoder, indent=2, sort_keys=True)
    logger.debug(f"Publish result data:\n{output_data}")
    if publish.output:
        with open(publish.output, mode="w") as fd:
            fd.write(output_data)

    return Publish(exit_code)


class _PublishJsonEncoder(json.JSONEncoder):
    safe_to_str_types = (Address,)

    def default(self, o):
        """Return a serializable object for o."""
        if is_dataclass(o):
            return asdict(o)
        if isinstance(o, collections.abc.Mapping):
            return dict(o)
        if isinstance(o, collections.abc.Sequence):
            return list(o)
        try:
            return super().default(o)
        except TypeError:
            return str(o)


@rule
async def package_for_publish(
    request: PublishProcessesRequest, local_environment: ChosenLocalEnvironmentName
) -> PublishProcesses:
    packages = await MultiGet(
        Get(BuiltPackage, EnvironmentAwarePackageRequest(field_set))
        for field_set in request.package_field_sets
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
            {
                field_set._request(packages): PublishRequest,
                local_environment.val: EnvironmentName,
            },
        )
        for field_set in request.publish_field_sets
    )

    # Flatten and dress each publish processes collection with data about its origin.
    publish_processes = [
        replace(
            publish_process,
            data=PublishOutputData({**publish_process.data, **field_set.get_output_data()}),
        )
        for processes, field_set in zip(publish, request.publish_field_sets)
        for publish_process in processes
    ]

    return PublishProcesses(publish_processes)


def rules():
    return collect_rules()
