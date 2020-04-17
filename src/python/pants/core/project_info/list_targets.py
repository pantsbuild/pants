# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Dict, cast

from pants.build_graph.address import Address
from pants.engine.addressable import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get
from pants.engine.target import DescriptionField, ProvidesField, Targets


class ListOptions(LineOriented, GoalSubsystem):
    """Lists all targets."""

    name = "list-v2"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--provides",
            type=bool,
            help=(
                "List only targets that provide an artifact, displaying the columns specified by "
                "--provides-columns."
            ),
        )
        register(
            "--provides-columns",
            default="address,artifact_id",
            help=(
                "Display these columns when --provides is specified. Available columns are: "
                "address, artifact_id, repo_name, repo_url, push_db_basedir"
            ),
        )
        register(
            "--documented",
            type=bool,
            help="Print only targets that are documented with a description.",
        )


class List(Goal):
    subsystem_cls = ListOptions


@goal_rule
async def list_targets(addresses: Addresses, options: ListOptions, console: Console) -> List:
    if not addresses.dependencies:
        console.print_stderr(f"WARNING: No targets were matched in goal `{options.name}`.")
        return List(exit_code=0)

    provides_enabled = options.values.provides
    documented_enabled = options.values.documented
    if provides_enabled and documented_enabled:
        raise ValueError(
            "Cannot specify both `--list-documented` and `--list-provides` at the same time. "
            "Please choose one."
        )

    if provides_enabled:
        targets = await Get[Targets](Addresses, addresses)
        addresses_with_provide_artifacts = {
            tgt.address: tgt[ProvidesField].value
            for tgt in targets
            if tgt.get(ProvidesField).value is not None
        }
        extractor_funcs = {
            "address": lambda address, _: address.spec,
            "artifact_id": lambda _, artifact: str(artifact),
            "repo_name": lambda _, artifact: artifact.repo.name,
            "repo_url": lambda _, artifact: artifact.repo.url,
            "push_db_basedir": lambda _, artifact: artifact.repo.push_db_basedir,
        }
        try:
            extractors = [
                extractor_funcs[col] for col in options.values.provides_columns.split(",")
            ]
        except KeyError:
            raise ValueError(
                "Invalid columns provided for `--list-provides-columns`: "
                f"{options.values.provides_columns}. Valid columns are: "
                f"{', '.join(sorted(extractor_funcs.keys()))}."
            )
        with options.line_oriented(console) as print_stdout:
            for address, artifact in addresses_with_provide_artifacts.items():
                print_stdout(" ".join(extractor(address, artifact) for extractor in extractors))
        return List(exit_code=0)

    if documented_enabled:
        targets = await Get[Targets](Addresses, addresses)
        addresses_with_descriptions = cast(
            Dict[Address, str],
            {
                tgt.address: tgt[DescriptionField].value
                for tgt in targets
                if tgt.get(DescriptionField).value is not None
            },
        )
        with options.line_oriented(console) as print_stdout:
            for address, description in addresses_with_descriptions.items():
                formatted_description = "\n  ".join(description.strip().split("\n"))
                print_stdout(f"{address.spec}\n  {formatted_description}")
        return List(exit_code=0)

    with options.line_oriented(console) as print_stdout:
        for address in sorted(addresses):
            print_stdout(address)
    return List(exit_code=0)


def rules():
    return [list_targets]
