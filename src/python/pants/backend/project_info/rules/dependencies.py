# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from enum import Enum
from typing import Set

from pants.backend.jvm.rules.targets import JarsField
from pants.backend.python.rules.targets import PythonRequirementsField
from pants.engine.addressable import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get
from pants.engine.target import Dependencies as DependenciesField
from pants.engine.target import Targets, TransitiveTargets
from pants.util.ordered_set import FrozenOrderedSet


class DependencyType(Enum):
    SOURCE = "source"
    THIRD_PARTY = "3rdparty"
    SOURCE_AND_THIRD_PARTY = "source-and-3rdparty"


# TODO(#8762) Get this rule to feature parity with the dependencies task.
class DependenciesOptions(LineOriented, GoalSubsystem):
    """Print the target's dependencies."""

    name = "dependencies2"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--transitive",
            default=False,
            type=bool,
            help=(
                "Run dependencies against transitive dependencies of targets specified on the "
                "command line."
            ),
        )
        register(
            "--type",
            type=DependencyType,
            default=DependencyType.SOURCE,
            help=(
                "Which types of dependencies to find, where `source` means source code "
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
        targets = await Get[Targets](
            Addresses(
                itertools.chain.from_iterable(
                    tgt.get(DependenciesField).value or () for tgt in target_roots
                )
            )
        )

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
