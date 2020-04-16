# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import itertools
import os
from abc import ABCMeta
from dataclasses import dataclass
from typing import Iterable, Type

from pants.base.build_root import BuildRoot
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.objects import union
from pants.engine.rules import UnionMembership, goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Configuration, RegisteredTargetTypes, Targets
from pants.rules.core.distdir import DistDir


class AWSLambdaError(Exception):
    pass


@dataclass(frozen=True)
class CreatedAWSLambda:
    digest: Digest
    name: str


@union
class AWSLambdaConfiguration(Configuration, metaclass=ABCMeta):
    """The fields necessary to create an AWS Lambda from a target."""


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
    registered_target_types: RegisteredTargetTypes,
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
        all_valid_target_types = itertools.chain.from_iterable(
            config_type.valid_target_types(
                registered_target_types.types, union_membership=union_membership
            )
            for config_type in config_types
        )
        formatted_target_types = sorted(target_type.alias for target_type in all_valid_target_types)
        raise ValueError(
            f"None of the provided targets work with the goal `{options.name}`. This goal "
            f"works with the following target types: {formatted_target_types}."
        )

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
