# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta
from dataclasses import dataclass
from textwrap import dedent

from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.fs import Digest, MergeDigests, Workspace
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
    zip_file_relpath: str
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
    console: Console, options: AWSLambdaOptions, distdir: DistDir, workspace: Workspace,
) -> AWSLambdaGoal:
    targets_to_valid_field_sets = await Get(
        TargetsToValidFieldSets,
        TargetsToValidFieldSetsRequest(
            AWSLambdaFieldSet,
            goal_description=f"the `{options.name}` goal",
            error_if_no_valid_targets=True,
        ),
    )
    awslambdas = await MultiGet(
        Get(CreatedAWSLambda, AWSLambdaFieldSet, field_set)
        for field_set in targets_to_valid_field_sets.field_sets
    )
    merged_digest = await Get(Digest, MergeDigests(awslambda.digest for awslambda in awslambdas))
    workspace.write_digest(merged_digest, path_prefix=str(distdir.relpath))
    with options.line_oriented(console) as print_stdout:
        for awslambda in awslambdas:
            output_path = distdir.relpath / awslambda.zip_file_relpath
            print_stdout(
                dedent(
                    f"""\
                    Wrote code bundle to {output_path}
                      Runtime: {awslambda.runtime}
                      Handler: {awslambda.handler}
                    """
                )
            )
    return AWSLambdaGoal(exit_code=0)


def rules():
    return [create_awslambda]
