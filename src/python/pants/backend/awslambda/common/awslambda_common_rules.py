# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import dataclasses
import os
from abc import ABC
from dataclasses import dataclass
from typing import ClassVar, Dict, Iterable, Tuple, Type

from pants.base.build_root import BuildRoot
from pants.build_graph.address import Address
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.objects import union
from pants.engine.rules import UnionMembership, goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Field, Target, Targets
from pants.rules.core.distdir import DistDir


class AWSLambdaError(Exception):
    pass


@dataclass(frozen=True)
class CreatedAWSLambda:
    digest: Digest
    name: str


# TODO: Factor up once done porting `setup-py2` and `fmt`/`lint`.
@union
@dataclass(frozen=True)
class AWSLambdaConfiguration(ABC):
    """An ad hoc collection of the fields necessary to create an AWS Lambda from a target."""

    required_fields: ClassVar[Tuple[Type[Field], ...]]

    address: Address

    @classmethod
    def is_valid(cls, tgt: Target) -> bool:
        return tgt.has_fields(cls.required_fields)

    @classmethod
    def create(cls, tgt: Target) -> "AWSLambdaConfiguration":
        all_expected_fields: Dict[str, Type[Field]] = {
            dataclass_field.name: dataclass_field.type
            for dataclass_field in dataclasses.fields(cls)
            if issubclass(dataclass_field.type, Field)
        }
        return cls(  # type: ignore[call-arg]
            address=tgt.address,
            **{
                dataclass_field_name: (
                    tgt[field_cls] if field_cls in cls.required_fields else tgt.get(field_cls)
                )
                for dataclass_field_name, field_cls in all_expected_fields.items()
            },
        )


class AWSLambdaOptions(LineOriented, GoalSubsystem):
    """Generate an AWS Lambda."""

    name = "awslambda"


class AWSLambdaGoal(Goal):
    subsystem_cls = AWSLambdaOptions


@goal_rule
async def create_awslambda(
    targets: Targets,
    console: Console,
    options: AWSLambdaOptions,
    union_membership: UnionMembership,
    distdir: DistDir,
    buildroot: BuildRoot,
    workspace: Workspace,
) -> AWSLambdaGoal:
    config_types: Iterable[Type[AWSLambdaConfiguration]] = union_membership.union_rules[
        AWSLambdaConfiguration
    ]
    configs = tuple(
        config_type.create(tgt)
        for tgt in targets
        for config_type in config_types
        if config_type.is_valid(tgt)
    )
    if not configs:
        console.print_stderr("No valid...")
        return AWSLambdaGoal(exit_code=1)

    awslambdas = await MultiGet(
        Get[CreatedAWSLambda](AWSLambdaConfiguration, config) for config in configs
    )
    merged_digest = await Get[Digest](
        DirectoriesToMerge(tuple(awslambda.digest for awslambda in awslambdas))
    )
    result = workspace.materialize_directory(
        DirectoryToMaterialize(merged_digest, path_prefix=str(distdir.relpath))
    )
    with options.line_oriented(console) as print_stdout:
        for path in result.output_paths:
            print_stdout(f"Wrote {os.path.relpath(path, buildroot.path)}")
    return AWSLambdaGoal(exit_code=0)


def rules():
    return [create_awslambda]
