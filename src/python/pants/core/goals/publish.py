# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from dataclasses import dataclass
from typing import ClassVar, Iterable, List, Tuple, Type, cast

from pants.build_graph.address import Address
from pants.core.goals.package import BuiltPackage, PackageFieldSet
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.selectors import MultiGet
from pants.engine.rules import Get, collect_rules, goal_rule
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    FieldSet,
    SpecialCasedDependencies,
    Target,
    Targets,
)
from pants.engine.unions import UnionMembership, union
from pants.util.meta import frozen_after_init
from pants.util.ordered_set import FrozenOrderedSet

logger = logging.getLogger(__name__)


class PublishTargetField(SpecialCasedDependencies):
    alias = "publish_targets"
    help = "Repositories to publish to."


@dataclass(frozen=True)
class PublishTargetFieldSet(FieldSet):
    required_fields = (PublishTargetField,)


@union
@dataclass(frozen=True)
class PublishRequest:
    built_package: BuiltPackage
    fieldset: PublishTargetFieldSet
    publish_target: "PublishTarget"


class PublishTarget(Target):
    core_fields = (*COMMON_TARGET_FIELDS,)

    publish_request_type: ClassVar[Type[PublishRequest]]
    publishee_fieldset_type: ClassVar[Type[PublishTargetFieldSet]] = PublishTargetFieldSet


class PublishSubsystem(GoalSubsystem):
    name = "publish"
    help = "Publish packages."


class Publish(Goal):
    subsystem_cls = PublishSubsystem


@dataclass(frozen=True)
class PublishedPackage:
    package: BuiltPackage
    publish_target: Address


@frozen_after_init
@dataclass(unsafe_hash=True)
class PublishedPackageSet:
    publishes: FrozenOrderedSet[PublishedPackage]

    def __init__(self, published_packages: Iterable[PublishedPackage]):
        self.publishes = FrozenOrderedSet(published_packages)


def _can_package(target: Target, union_membership: UnionMembership):
    package_request_types = cast(Iterable[Type[PackageFieldSet]], union_membership[PackageFieldSet])

    for fieldset in package_request_types:
        if fieldset.is_applicable(target):
            return fieldset

    return False


@goal_rule
async def publish(
    targets: Targets,
    union_membership: UnionMembership,
) -> Publish:
    publishable_targets: List[Tuple[Target, PackageFieldSet]] = []

    # Retrieve publishable targets and their package type.
    for target in targets:
        if PublishTargetFieldSet.is_applicable(target):
            package_fieldset = _can_package(target, union_membership)
            if package_fieldset:
                publishable_targets.append((target, package_fieldset))
            else:
                logger.warn(
                    f"Unable to publish {target.address} as it is not a packageable target."
                )
                return Publish(exit_code=1)

    # Get the publish targets (destination)
    publish_targets_set = cast(
        Iterable[Iterable[PublishTarget]],
        await MultiGet(
            Get(
                Targets,
                UnparsedAddressInputs,
                publishable[PublishTargetField].to_unparsed_address_inputs(),
            )
            for (publishable, _) in publishable_targets
        ),
    )

    # get the built packages.
    built_packages = await MultiGet(
        Get(BuiltPackage, PackageFieldSet, package_fieldset.create(target))
        for (target, package_fieldset) in publishable_targets
    )

    # Build a list of requests, ensuring that the publishable is valid for the
    # publish target. Error if not.
    requests: List[PublishRequest] = []

    for (target, _), publish_targets, built_package in zip(
        publishable_targets, publish_targets_set, built_packages
    ):
        for publish_target in publish_targets:
            if not publish_target.publishee_fieldset_type.is_applicable(target):
                logger.warn(f"Cannot publish {target.address} to {publish_target.address}.")
                return Publish(exit_code=1)
            fieldset = publish_target.publishee_fieldset_type.create(target)

            logger.info(f"Publishing {target.address} to {publish_target.address}")
            requests.append(
                publish_target.publish_request_type(
                    built_package,
                    fieldset,
                    publish_target,
                )
            )

    packages = await MultiGet(
        Get(PublishedPackage, PublishRequest, request) for request in requests
    )

    # ???
    PublishedPackageSet(packages)

    return Publish(exit_code=0)


def rules():
    return collect_rules()
