# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Union

from pants.engine.addressable import Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.legacy.graph import HydratedTargets
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get


class ListOptions(LineOriented, GoalSubsystem):
    """Lists all targets matching the target specs."""

    name = "list"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--provides",
            type=bool,
            help="List only targets that provide an artifact, displaying the columns specified by "
            "--provides-columns.",
        )
        register(
            "--provides-columns",
            default="address,artifact_id",
            help="Display these columns when --provides is specified. Available columns are: "
            "address, artifact_id, repo_name, repo_url, push_db_basedir",
        )
        register(
            "--documented",
            type=bool,
            help="Print only targets that are documented with a description.",
        )


class List(Goal):
    subsystem_cls = ListOptions


@goal_rule
async def list_targets(console: Console, list_options: ListOptions, addresses: Addresses) -> List:
    provides = list_options.values.provides
    provides_columns = list_options.values.provides_columns
    documented = list_options.values.documented
    collection: Union[HydratedTargets, Addresses]
    if provides or documented:
        # To get provides clauses or documentation, we need hydrated targets.
        collection = await Get[HydratedTargets](Addresses, addresses)
        if provides:
            extractors = dict(
                address=lambda adaptor: adaptor.address.spec,
                artifact_id=lambda adaptor: str(adaptor.provides),
                repo_name=lambda adaptor: adaptor.provides.repo.name,
                repo_url=lambda adaptor: adaptor.provides.repo.url,
                push_db_basedir=lambda adaptor: adaptor.provides.repo.push_db_basedir,
            )

            def print_provides(col_extractors, target):
                if getattr(target.adaptor, "provides", None):
                    return " ".join(extractor(target.adaptor) for extractor in col_extractors)

            try:
                column_extractors = [extractors[col] for col in (provides_columns.split(","))]
            except KeyError:
                raise Exception(
                    "Invalid columns specified: {0}. Valid columns are: address, artifact_id, "
                    "repo_name, repo_url, push_db_basedir.".format(provides_columns)
                )

            print_fn = lambda target: print_provides(column_extractors, target)
        else:

            def print_documented(target):
                description = getattr(target.adaptor, "description", None)
                if description:
                    return "{0}\n  {1}".format(
                        target.adaptor.address.spec, "\n  ".join(description.strip().split("\n"))
                    )

            print_fn = print_documented
    else:
        # Otherwise, we can use only addresses.
        collection = addresses
        print_fn = lambda address: address.spec

    with list_options.line_oriented(console) as print_stdout:
        if not collection.dependencies:
            console.print_stderr("WARNING: No targets were matched in goal `{}`.".format("list"))

        for item in collection:
            result = print_fn(item)
            if result:
                print_stdout(result)

    return List(exit_code=0)


def rules():
    return [list_targets]
