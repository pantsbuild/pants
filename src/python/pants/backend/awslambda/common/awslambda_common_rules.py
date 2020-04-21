# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from abc import ABCMeta
from dataclasses import dataclass

from pants.base.build_root import BuildRoot
from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import Configuration, RegisteredTargetTypes, TargetsWithOrigins
from pants.engine.unions import UnionMembership, union


class AWSLambdaError(Exception):
    pass


@dataclass(frozen=True)
class CreatedAWSLambda:
    digest: Digest
    name: str
    runtime: str
    handler: str


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
    targets_with_origins: TargetsWithOrigins,
    console: Console,
    options: AWSLambdaOptions,
    union_membership: UnionMembership,
    registered_target_types: RegisteredTargetTypes,
    distdir: DistDir,
    buildroot: BuildRoot,
    workspace: Workspace,
) -> AWSLambdaGoal:
    targets_to_valid_configs = AWSLambdaConfiguration.group_targets_to_valid_subclass_configs(
        targets_with_origins,
        union_membership=union_membership,
        registered_target_types=registered_target_types,
        goal_name=options.name,
        error_if_no_valid_targets=True,
    )
    awslambdas = await MultiGet(
        Get[CreatedAWSLambda](AWSLambdaConfiguration, config)
        for valid_configs in targets_to_valid_configs.values()
        for config in valid_configs
    )
    merged_digest = await Get[Digest](
        DirectoriesToMerge(tuple(awslambda.digest for awslambda in awslambdas))
    )
    result = workspace.materialize_directory(
        DirectoryToMaterialize(merged_digest, path_prefix=str(distdir.relpath))
    )
    with options.line_oriented(console) as print_stdout:
        for awslambda, path in zip(awslambdas, result.output_paths):
            print_stdout(f"Wrote code bundle to {os.path.relpath(path, buildroot.path)}")
            print_stdout(f"  Runtime: {awslambda.runtime}")
            print_stdout(f"  Handler: {awslambda.handler}")
            print_stdout("")
    return AWSLambdaGoal(exit_code=0)


def rules():
    return [create_awslambda]
