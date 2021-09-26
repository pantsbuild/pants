# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from enum import Enum
from typing import Set, cast

from pants.backend.project_info.depgraph import DependencyGraph, DependencyGraphRequest
from pants.engine.addresses import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import Get, collect_rules, goal_rule


class OutputFormat(Enum):
    TEXT = "text"
    JSON = "json"


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
                "Act on the transitive dependencies of the input targets. If unspecified, act "
                "only on the direct dependencies of the input targets."
            ),
        )
        register(
            "--format",
            type=OutputFormat,
            default=OutputFormat.TEXT,
            help=(
                "Output in this format. Possible values are:\n"
                "  - text: A single list of all the (optionally transitive) dependencies of the "
                "input targets.\n"
                "  - json: A structured representation of the dependencies of each input target "
                "(and optionally of their transitive dependencies)."
            ),
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
            "| xargs ./pants filter --target-type=python_requirement_library \\\n"
            "| xargs ./pants peek | jq -r '.[][\"requirements\"][]'\n",
            help=(
                "Which types of dependencies to list, where `source` means source code "
                "dependencies and `3rdparty` means third-party requirement strings. "
                "Only relevant for text output."
            ),
        )

    @property
    def transitive(self) -> bool:
        return cast(bool, self.options.transitive)

    @property
    def format(self) -> OutputFormat:
        return cast(OutputFormat, self.options.format)

    @property
    def type(self) -> DependencyType:
        return cast(DependencyType, self.options.type)


class Dependencies(Goal):
    subsystem_cls = DependenciesSubsystem


@goal_rule
async def dependencies(
    console: Console, addresses: Addresses, dependencies_subsystem: DependenciesSubsystem
) -> Dependencies:
    depgraph = await Get(
        DependencyGraph, DependencyGraphRequest(addresses, dependencies_subsystem.transitive)
    )

    if dependencies_subsystem.format == OutputFormat.TEXT:
        include_source = dependencies_subsystem.type in [
            DependencyType.SOURCE,
            DependencyType.SOURCE_AND_THIRD_PARTY,
        ]
        include_3rdparty = dependencies_subsystem.type in [
            DependencyType.THIRD_PARTY,
            DependencyType.SOURCE_AND_THIRD_PARTY,
        ]

        address_strings = set()
        third_party_requirements: Set[str] = set()
        for vertex in depgraph.vertices:
            for dep in depgraph.get_dependencies(vertex):
                if include_source:
                    address_strings.add(dep.data["address"])
                if include_3rdparty:
                    third_party_requirements.update(dep.data.get("requirements", []))

        with dependencies_subsystem.line_oriented(console) as print_stdout:
            for address in sorted(address_strings):
                print_stdout(address)
            for requirement_string in sorted(third_party_requirements):
                print_stdout(requirement_string)
    elif dependencies_subsystem.format == OutputFormat.JSON:
        console.print_stdout(depgraph.to_json())
    return Dependencies(exit_code=0)


def rules():
    return collect_rules()
