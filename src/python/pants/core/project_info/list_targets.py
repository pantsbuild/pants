# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
from enum import Enum
from typing import Callable, Dict, Optional, Union, cast

from pants.engine.addresses import Address, Addresses
from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.legacy.graph import FingerprintedTargetCollection, TransitiveFingerprintedTarget
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get
from pants.engine.target import DescriptionField, ProvidesField, Target, Targets


class ListOptions(LineOriented, GoalSubsystem):
    """Lists all targets matching the file or target arguments."""

    name = "list-v2"

    class OutputFormat(Enum):
        address_specs = "address-specs"
        provides = "provides"
        documented = "documented"
        json = "json"

    @classmethod
    def register_options(cls, register):
        super().register_options(register)
        register(
            "--provides",
            type=bool,
            removal_version="1.30.0.dev2",
            removal_hint="Use --output-format=provides instead!",
            help="List only targets that provide an artifact, displaying the columns specified by "
            "--provides-columns.",
        )
        register(
            "--provides-columns",
            default="address,artifact_id",
            help="Display these columns when --output-format=provides is specified. Available "
            "columns are: address, artifact_id, repo_name, repo_url, push_db_basedir",
        )

        register(
            "--documented",
            type=bool,
            removal_version="1.30.0.dev2",
            removal_hint="Use --output-format=documented instead!",
            help="Print only targets that are documented with a description.",
        )

        register(
            "--output-format",
            type=cls.OutputFormat,
            default=cls.OutputFormat.address_specs,
            help="How to format targets when printed to stdout.",
        )


PrintFunction = Callable[[Target], Optional[str]]


def _make_provides_print_fn(provides_columns: str, targets: Targets) -> PrintFunction:
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
        column_extractors = [
            extractor_funcs[col] for col in provides_columns.split(",")
        ]
    except KeyError:
        raise ValueError(
            "Invalid columns provided for `--list-provides-columns`: "
            f"{provides_columns}. Valid columns are: "
            f"{', '.join(sorted(extractor_funcs.keys()))}."
        )

    try:
        column_extractors = [extractor_funcs[col] for col in (provides_columns.split(","))]
    except KeyError:
        raise Exception(
            "Invalid columns specified: {0}. Valid columns are: address, artifact_id, "
            "repo_name, repo_url, push_db_basedir.".format(provides_columns)
        )

    def print_provides(target: Target) -> Optional[str]:
        address = target.address
        artifact = addresses_with_provide_artifacts.get(address, None)
        if artifact:
            return " ".join(extractor(address, artifact) for extractor in column_extractors)
        return None

    return print_provides


def _make_print_documented_target(targets: Targets) -> PrintFunction:
    addresses_with_descriptions = cast(
        Dict[Address, str],
        {
            tgt.address: tgt[DescriptionField].value
            for tgt in targets
            if tgt.get(DescriptionField).value is not None
        },
    )
    def print_documented(target: Target) -> Optional[str]:
        address = target.address
        description = addresses_with_descriptions.get(address, None)
        if description:
            formatted_description = "\n  ".join(description.strip().split("\n"))
            return f"{address.spec}\n  {formatted_description}"
        return None
    return print_documented


FingerprintedPrintFunction = Callable[[TransitiveFingerprintedTarget], str]


def _print_fingerprinted_target(fingerprinted_target: TransitiveFingerprintedTarget) -> str:
    was_root = fingerprinted_target.was_root
    address = fingerprinted_target.address.spec
    target_type = fingerprinted_target.type_alias
    intransitive_fingerprint = fingerprinted_target.intransitive_fingerprint_arg
    transitive_fingerprint = fingerprinted_target.transitive_fingerprint_arg
    return json.dumps(
        {
            "was_root": was_root,
            "address": address,
            "target_type": target_type,
            "intransitive_fingerprint": intransitive_fingerprint,
            "transitive_fingerprint": transitive_fingerprint,
        }
    )


AddressesPrintFunction = Callable[[Address], str]


class List(Goal):
    subsystem_cls = ListOptions


@goal_rule
async def list_targets(console: Console, list_options: ListOptions, addresses: Addresses) -> List:
    provides = list_options.values.provides
    provides_columns = list_options.values.provides_columns
    documented = list_options.values.documented
    collection: Union[Targets, Addresses, FingerprintedTargetCollection]
    print_fn: Union[PrintFunction, FingerprintedPrintFunction, AddressesPrintFunction]

    output_format = list_options.values.output_format

    # TODO: Remove when these options have completed their deprecation cycle!
    if provides:
        output_format = ListOptions.OutputFormat.provides
    elif documented:
        output_format = ListOptions.OutputFormat.documented

    # TODO: a match() method for Enums which allows `await Get()` within it somehow!
    if output_format == ListOptions.OutputFormat.provides:
        # To get provides clauses, we need hydrated targets.
        collection = await Get[Targets](Addresses, addresses)
        print_fn = _make_provides_print_fn(provides_columns, collection)
    elif output_format == ListOptions.OutputFormat.documented:
        # To get documentation, we need hydrated targets.
        collection = await Get[Targets](Addresses, addresses)
        print_fn = _make_print_documented_target(collection)
    elif output_format == ListOptions.OutputFormat.json:
        # To get fingerprints of each target and its dependencies, we have to request that information
        # specifically.
        collection = await Get[FingerprintedTargetCollection](Addresses, addresses)
        print_fn = _print_fingerprinted_target
    else:
        assert output_format == ListOptions.OutputFormat.address_specs
        # Otherwise, we can use only addresses.
        collection = addresses
        print_fn = lambda address: address.spec

    with list_options.line_oriented(console) as print_stdout:
        if not collection.dependencies:
            console.print_stderr("WARNING: No targets were matched in goal `{}`.".format("list"))

        for item in collection:
            # The above waterfall of `if` conditionals using the ListOptions.OutputFormat enum
            # should ensure that the types of `collection` and `print_fn` are matched up.
            result = print_fn(item) # type: ignore[arg-type]
            if result:
                print_stdout(result)

    return List(exit_code=0)


def rules():
    return [list_targets]
