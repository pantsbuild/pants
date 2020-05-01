# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from abc import ABCMeta
from dataclasses import dataclass

from pants.base.build_root import BuildRoot
from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoryToMaterialize, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import goal_rule
from pants.engine.selectors import Get, MultiGet
from pants.engine.target import FieldSet, TargetsToValidFieldSets, TargetsToValidFieldSetsRequest
from pants.engine.unions import union


class AWSLambdaError(Exception):
    pass


@dataclass(frozen=True)
class CreatedAWSLambda:
    digest: Digest
    name: str
    runtime: str
    handler: str


@union
class AWSLambdaFieldSet(FieldSet, metaclass=ABCMeta):
    """The fields necessary to create an AWS Lambda from a target."""


class AWSLambdaOptions(LineOriented, GoalSubsystem):
    """Generate an AWS Lambda."""

    name = "awslambda"


class AWSLambdaGoal(Goal):
    subsystem_cls = AWSLambdaOptions


@goal_rule
async def create_awslambda(
    console: Console,
    options: AWSLambdaOptions,
    distdir: DistDir,
    buildroot: BuildRoot,
    workspace: Workspace,
) -> AWSLambdaGoal:
    targets_to_valid_field_sets = await Get[TargetsToValidFieldSets](
        TargetsToValidFieldSetsRequest(
            AWSLambdaFieldSet,
            goal_description=f"the `{options.name}` goal",
            error_if_no_valid_targets=True,
        )
    )
    awslambdas = await MultiGet(
        Get[CreatedAWSLambda](AWSLambdaFieldSet, field_set)
        for field_set in targets_to_valid_field_sets.field_sets
    )
    merged_digest = await Get[Digest](MergeDigests(awslambda.digest for awslambda in awslambdas))
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
