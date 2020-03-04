# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum
from typing import Set

from pants.engine.addressable import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.legacy.graph import HydratedTargets, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonRequirementLibraryAdaptor
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get


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
            help="Run dependencies against transitive dependencies of targets specified on the command line.",
        )
        register(
            "--type",
            type=DependencyType,
            default=DependencyType.SOURCE,
            help="Which types of dependencies to find, where `source` means source code dependencies "
            "and `3rdparty` means third-party requirements and JARs.",
        )


class Dependencies(Goal):
    subsystem_cls = DependenciesOptions


@goal_rule
async def dependencies(
    console: Console, addresses: Addresses, options: DependenciesOptions,
) -> Dependencies:
    address_strings: Set[str] = set()
    third_party_requirements: Set[str] = set()

    if options.values.transitive:
        transitive_targets = await Get[TransitiveHydratedTargets](Addresses, addresses)
        hydrated_targets = HydratedTargets(
            transitive_targets.closure - set(transitive_targets.roots)
        )
    else:
        hydrated_targets = await Get[HydratedTargets](Addresses, addresses)

    should_include_third_party = options.values.type in [
        DependencyType.THIRD_PARTY,
        DependencyType.SOURCE_AND_THIRD_PARTY,
    ]
    should_include_source = options.values.type in [
        DependencyType.SOURCE,
        DependencyType.SOURCE_AND_THIRD_PARTY,
    ]

    for target in hydrated_targets:
        if should_include_third_party:
            if isinstance(target.adaptor, PythonRequirementLibraryAdaptor):
                third_party_requirements.update(
                    str(requirement.requirement) for requirement in target.adaptor.requirements
                )
                # TODO(#8762): Support jvm third party deps when there is some sort of JarLibraryAdaptor.
        if should_include_source:
            address_strings.update(
                hydrated_target.adaptor.address.spec for hydrated_target in hydrated_targets
            )

    with options.line_oriented(console) as print_stdout:
        for address in sorted(address_strings):
            print_stdout(address)
        for requirement_string in sorted(third_party_requirements):
            print_stdout(requirement_string)

    return Dependencies(exit_code=0)


def rules():
    return [
        dependencies,
    ]
