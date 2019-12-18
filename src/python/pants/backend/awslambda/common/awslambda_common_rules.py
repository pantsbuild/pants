# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.build_graph.address import Address
from pants.engine.addressable import BuildFileAddresses
from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem, LineOriented
from pants.engine.legacy.graph import HydratedTarget
from pants.engine.rules import console_rule, rule, union
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.distdir import DistDir


class AWSLambdaError(Exception):
  pass


@dataclass(frozen=True)
class CreatedAWSLambda:
  digest: Digest
  name: str


@union
class AWSLambdaTarget:
  pass


class AWSLambdaOptions(LineOriented, GoalSubsystem):
  """Runs tests."""
  name = "awslambda"


class AWSLambdaGoal(Goal):
  """Generate an AWS Lambda."""
  subsystem_cls = AWSLambdaOptions


@console_rule
async def create_awslambda(
    addresses: BuildFileAddresses,
    console: Console,
    options: AWSLambdaOptions,
    distdir: DistDir,
    workspace: Workspace) -> AWSLambdaGoal:
  with options.line_oriented(console) as print_stdout:
    print_stdout(f"Generating AWS lambdas in `./{distdir.relpath}`")
    awslambdas = await MultiGet(Get[CreatedAWSLambda](Address, address.to_address())
                                for address in addresses)
    merged_digest = await Get[Digest](
      DirectoriesToMerge(tuple(awslambda.digest for awslambda in awslambdas))
    )
    result = workspace.materialize_directory(
      DirectoryToMaterialize(merged_digest, path_prefix=str(distdir.relpath))
    )
    for path in result.output_paths:
      print_stdout(f"Wrote {path}")
  return AWSLambdaGoal(exit_code=0)


@rule
async def coordinator_of_lambdas(target: HydratedTarget) -> CreatedAWSLambda:
  awslambda = await Get[CreatedAWSLambda](AWSLambdaTarget, target.adaptor)
  return awslambda


def rules():
  return [create_awslambda, coordinator_of_lambdas]
