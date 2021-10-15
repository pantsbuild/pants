# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
from enum import Enum
from typing import Set, cast

from pants.backend.python.target_types import PythonRequirementsField
from pants.engine.addresses import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import Dependencies as DependenciesField
from pants.engine.target import (
    DependenciesRequest,
    Targets,
    TransitiveTargets,
    TransitiveTargetsRequest,
    UnexpandedTargets,
)


class DependencyType(Enum):
    SOURCE = "source"
    THIRD_PARTY = "3rdparty"
    SOURCE_AND_THIRD_PARTY = "source-and-3rdparty"


class DependenciesSubsystem(LineOriented, GoalSubsystem):
    name = "dependencies"
    help = "List the dependencies of the input files/targets."

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
            "--closed",
            type=bool,
            default=False,
            help="Include the input targets in the output, along with the dependencies.",
        )
        register(
            "--type",
            type=DependencyType,
            default=DependencyType.SOURCE,
            removal_version="2.9.0.dev0",
            removal_hint="This option is misleading and not very useful. In the future there "
            "will be a more robust way of querying and filtering dependencies.\nMeanwhile you "
            "can get the list of requirement strings for a set of targets using something like\n\n"
            "./pants dependencies :: \\\n"
            "| xargs ./pants filter --target-type=python_requirement \\\n"
            "| xargs ./pants peek | jq -r '.[][\"requirements\"][]'\n",
            help=(
                "Which types of dependencies to list, where `source` means source code "
                "dependencies and `3rdparty` means third-party requirement strings."
            ),
        )

    @property
    def transitive(self) -> bool:
        return cast(bool, self.options.transitive)

    @property
    def closed(self) -> bool:
        return cast(bool, self.options.closed)

    @property
    def type(self) -> DependencyType:
        return cast(DependencyType, self.options.type)


class Dependencies(Goal):
    subsystem_cls = DependenciesSubsystem


@goal_rule
async def dependencies(
    console: Console, addresses: Addresses, dependencies_subsystem: DependenciesSubsystem
) -> Dependencies:
    if dependencies_subsystem.transitive:
        transitive_targets = await Get(
            TransitiveTargets, TransitiveTargetsRequest(addresses, include_special_cased_deps=True)
        )
        targets = Targets(transitive_targets.dependencies)
    else:
        # NB: We must preserve target generators for the roots, i.e. not replace with their
        # generated targets.
        target_roots = await Get(UnexpandedTargets, Addresses, addresses)
        # NB: When determining dependencies, though, we replace target generators with their
        # generated targets.
        dependencies_per_target_root = await MultiGet(
            Get(
                Targets,
                DependenciesRequest(tgt.get(DependenciesField), include_special_cased_deps=True),
            )
            for tgt in target_roots
        )
        targets = Targets(itertools.chain.from_iterable(dependencies_per_target_root))

    include_source = dependencies_subsystem.type in [
        DependencyType.SOURCE,
        DependencyType.SOURCE_AND_THIRD_PARTY,
    ]
    include_3rdparty = dependencies_subsystem.type in [
        DependencyType.THIRD_PARTY,
        DependencyType.SOURCE_AND_THIRD_PARTY,
    ]

    address_strings = {addr.spec for addr in addresses} if dependencies_subsystem.closed else set()
    third_party_requirements: Set[str] = set()
    for tgt in targets:
        if include_source:
            address_strings.add(tgt.address.spec)
        if include_3rdparty:
            if tgt.has_field(PythonRequirementsField):
                third_party_requirements.update(
                    str(python_req) for python_req in tgt[PythonRequirementsField].value
                )

    with dependencies_subsystem.line_oriented(console) as print_stdout:
        for address in sorted(address_strings):
            print_stdout(address)
        for requirement_string in sorted(third_party_requirements):
            print_stdout(requirement_string)

    return Dependencies(exit_code=0)


def rules():
    return collect_rules()
