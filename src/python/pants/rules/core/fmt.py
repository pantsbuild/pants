# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import Tuple

from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import ExecuteProcessResult
from pants.engine.legacy.graph import HydratedTargets
from pants.engine.legacy.structs import TargetAdaptor
from pants.engine.rules import UnionMembership, console_rule, union
from pants.engine.selectors import Get, MultiGet


@dataclass(frozen=True)
class FmtResult:
  digest: Digest
  stdout: str
  stderr: str

  @staticmethod
  def from_execute_process_result(process_result: ExecuteProcessResult) -> "FmtResult":
    return FmtResult(
      digest=process_result.output_directory_digest,
      stdout=process_result.stdout.decode(),
      stderr=process_result.stderr.decode(),
    )


@dataclass(frozen=True)
class AggregatedFmtResults:
  """This collection allows us to safely aggregate multiple `FmtResult`s for a language.

  The `combined_digest` is used to ensure that none of the formatters overwrite each other. The
  language implementation should run each formatter one at a time and pipe the resulting digest of
  one formatter into the next. The `combined_digest` must contain all files for the target,
  including any which were not re-formatted."""
  results: Tuple[FmtResult, ...]
  combined_digest: Digest


@union
class FormatTarget:
  """A union for registration of a formattable target type."""

  @staticmethod
  def is_formattable(
    target_adaptor: TargetAdaptor, *, union_membership: UnionMembership
  ) -> bool:
    return (
      union_membership.is_member(FormatTarget, target_adaptor)
      # TODO: make TargetAdaptor return a 'sources' field with an empty snapshot instead of
      #  raising to remove the hasattr() checks here!
      and hasattr(target_adaptor, "sources")
      and target_adaptor.sources.snapshot.files  # i.e., sources is not empty
    )


class FmtOptions(GoalSubsystem):
  """Autoformat source code."""

  # TODO: make this "fmt"
  # Blocked on https://github.com/pantsbuild/pants/issues/8351
  name = 'fmt2'


class Fmt(Goal):
  subsystem_cls = FmtOptions


@console_rule
async def fmt(
  console: Console,
  targets: HydratedTargets,
  workspace: Workspace,
  union_membership: UnionMembership
) -> Fmt:
  aggregated_results = await MultiGet(
    Get[AggregatedFmtResults](FormatTarget, target.adaptor)
    for target in targets
    if FormatTarget.is_formattable(target.adaptor, union_membership=union_membership)
  )
  individual_results = [
    result
    for aggregated_result in aggregated_results
    for result in aggregated_result.results
  ]

  if not individual_results:
    return Fmt(exit_code=0)

  # NB: this will fail if there are any conflicting changes, which we want to happen rather than
  # silently having one result override the other. In practicality, this should never happen due
  # to our use of an aggregator rule for each distinct language.
  merged_formatted_digest = await Get[Digest](
    DirectoriesToMerge(
      tuple(aggregated_result.combined_digest for aggregated_result in aggregated_results)
    )
  )
  workspace.materialize_directory(DirectoryToMaterialize(merged_formatted_digest))
  for result in individual_results:
    if result.stdout:
      console.print_stdout(result.stdout)
    if result.stderr:
      console.print_stderr(result.stderr)

  # Since the rules to produce FmtResult should use ExecuteRequest, rather than
  # FallibleExecuteProcessRequest, we assume that there were no failures.
  return Fmt(exit_code=0)


def rules():
  return [
    fmt,
  ]
