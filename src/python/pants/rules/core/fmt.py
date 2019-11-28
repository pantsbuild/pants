# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoriesToMerge, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal
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


@union
class TargetWithSources:
  """A union for registration of a formattable target type."""

  @staticmethod
  def is_formattable_and_lintable(
    target_adaptor: TargetAdaptor, *, union_membership: UnionMembership
  ) -> bool:
    return (
      union_membership.is_member(TargetWithSources, target_adaptor)
      # TODO: make TargetAdaptor return a 'sources' field with an empty snapshot instead of
      #  raising to remove the hasattr() checks here!
      and hasattr(target_adaptor, "sources")
      and target_adaptor.sources.snapshot.files  # i.e., sources is not empty
    )


class Fmt(Goal):
  """Autoformat source code."""

  # TODO: make this "fmt"
  # Blocked on https://github.com/pantsbuild/pants/issues/8351
  name = 'fmt-v2'


@console_rule
async def fmt(
  console: Console,
  targets: HydratedTargets,
  workspace: Workspace,
  union_membership: UnionMembership
) -> Fmt:
  results = await MultiGet(
    Get[FmtResult](TargetWithSources, target.adaptor)
    for target in targets
    if TargetWithSources.is_formattable_and_lintable(
      target.adaptor, union_membership=union_membership
    )
  )

  if not results:
    return Fmt(exit_code=0)

  # NB: this will fail if there are any conflicting changes, which we want to happen rather than
  # silently having one result override the other.
  # TODO(#8722): how should we handle multiple auto-formatters touching the same files?
  merged_formatted_digest = await Get[Digest](
    DirectoriesToMerge(tuple(result.digest for result in results))
  )
  workspace.materialize_directory(DirectoryToMaterialize(merged_formatted_digest))
  for result in results:
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
