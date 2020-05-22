# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from enum import Enum
from typing import Set

from pants.backend.jvm.target_types import JarsField
from pants.backend.python.target_types import PythonRequirementsField
from pants.engine.addresses import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Dependencies as DependenciesField
from pants.engine.target import DependenciesRequest, Targets, TransitiveTargets
from pants.util.ordered_set import FrozenOrderedSet


class DependencyType(Enum):
    SOURCE = "source"
    THIRD_PARTY = "3rdparty"
    SOURCE_AND_THIRD_PARTY = "source-and-3rdparty"


class DependenciesOptions(LineOriented, GoalSubsystem):
    """List the dependencies of the input targets."""

    name = "dependencies2"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--transitive",
            default=False,
            type=bool,
            help=(
                "List all transitive dependencies. If unspecified, list direct dependencies only."
            ),
        )
        register(
            "--type",
            type=DependencyType,
            default=DependencyType.SOURCE,
            help=(
                "Which types of dependencies to list, where `source` means source code "
                "dependencies and `3rdparty` means third-party requirements and JARs."
            ),
        )


class Dependencies(Goal):
    subsystem_cls = DependenciesOptions


@goal_rule
async def dependencies(
    console: Console, addresses: Addresses, options: DependenciesOptions,
) -> Dependencies:
    if options.values.transitive:
        transitive_targets = await Get[TransitiveTargets](Addresses, addresses)
        targets = Targets(transitive_targets.closure - FrozenOrderedSet(transitive_targets.roots))
    else:
        target_roots = await Get[Targets](Addresses, addresses)
        dependencies_per_target_root = await MultiGet(
            Get[Targets](DependenciesRequest(tgt.get(DependenciesField))) for tgt in target_roots
        )
        targets = Targets(itertools.chain.from_iterable(dependencies_per_target_root))

    include_3rdparty = options.values.type in [
        DependencyType.THIRD_PARTY,
        DependencyType.SOURCE_AND_THIRD_PARTY,
    ]
    include_source = options.values.type in [
        DependencyType.SOURCE,
        DependencyType.SOURCE_AND_THIRD_PARTY,
    ]

    address_strings = set()
    third_party_requirements: Set[str] = set()
    for tgt in targets:
        if include_source:
            address_strings.add(tgt.address.spec)
        if include_3rdparty:
            if tgt.has_field(PythonRequirementsField):
                third_party_requirements.update(
                    str(python_req.requirement) for python_req in tgt[PythonRequirementsField].value
                )
            if tgt.has_field(JarsField):
                third_party_requirements.update(
                    (
                        f"{jar.org}:{jar.name}:{jar.rev}"
                        if jar.rev is not None
                        else f"{jar.org}:{jar.name}"
                    )
                    for jar in tgt[JarsField].value
                )

    with options.line_oriented(console) as print_stdout:
        for address in sorted(address_strings):
            print_stdout(address)
        for requirement_string in sorted(third_party_requirements):
            print_stdout(requirement_string)

    return Dependencies(exit_code=0)


def rules():
    return [dependencies]
