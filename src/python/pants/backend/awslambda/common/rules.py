# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import logging
from abc import ABCMeta
from dataclasses import dataclass
from textwrap import dedent

from pants.core.util_rules.distdir import DistDir
from pants.engine.console import Console
from pants.engine.fs import Digest, MergeDigests, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.rules import Get, MultiGet, collect_rules, goal_rule
from pants.engine.target import FieldSet, TargetRootsToFieldSets, TargetRootsToFieldSetsRequest
from pants.engine.unions import union

logger = logging.getLogger(__name__)


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


class AWSLambdaSubsystem(LineOriented, GoalSubsystem):
    """Deprecated in favor of the `package` goal."""

    name = "awslambda"


class AWSLambdaGoal(Goal):
    subsystem_cls = AWSLambdaSubsystem


@goal_rule
async def create_awslambda(
    console: Console,
    awslambda_subsystem: AWSLambdaSubsystem,
    distdir: DistDir,
    workspace: Workspace,
) -> AWSLambdaGoal:
    logger.warning(
        "The `awslambda` goal is deprecated in favor of the `package` goal, which behaves "
        "identically. `awslambda` will be removed in 2.1.0.dev0."
    )
    targets_to_valid_field_sets = await Get(
        TargetRootsToFieldSets,
        TargetRootsToFieldSetsRequest(
            AWSLambdaFieldSet,
            goal_description="the `awslambda` goal",
            error_if_no_applicable_targets=True,
        ),
    )
    awslambdas = await MultiGet(
        Get(CreatedAWSLambda, AWSLambdaFieldSet, field_set)
        for field_set in targets_to_valid_field_sets.field_sets
    )
    merged_digest = await Get(Digest, MergeDigests(awslambda.digest for awslambda in awslambdas))
    workspace.write_digest(merged_digest, path_prefix=str(distdir.relpath))
    with awslambda_subsystem.line_oriented(console) as print_stdout:
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
    return collect_rules()
