# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.console import Console
from pants.engine.fs import Digest, DirectoryToMaterialize, Workspace
from pants.engine.goal import Goal
from pants.engine.legacy.graph import HydratedTargets
from pants.engine.rules import UnionMembership, console_rule, union
from pants.engine.selectors import Get, MultiGet


@dataclass(frozen=True)
class FmtResult:
  digest: Digest
  stdout: str
  stderr: str


@union
class TargetWithSources:
  """A union for registration of a formattable target type."""


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
    # TODO: make TargetAdaptor return a 'sources' field with an empty snapshot instead of
    # raising to remove the hasattr() checks here!
    if union_membership.is_member(TargetWithSources, target.adaptor) and hasattr(target.adaptor, "sources")
  )

  for result in results:
    # NB: we cannot call `workspace.materialize_directories()` in one single call with all of the
    # results because results can override each other—they share the same path prefix of `./` and
    # are capable of changing the same files. We must instead call
    # `workspace.materialize_directory()` for every result. If two results make conflicting
    # changes, one will get overridden by the other.
    workspace.materialize_directory(DirectoryToMaterialize(result.digest))
    if result.stdout:
      console.print_stdout(result.stdout)
    if result.stderr:
      console.print_stderr(result.stderr)

  # Since the rules to produce FmtResult should use ExecuteRequest, rather than
  # FallibleExecuteProcessRequest, we assume that there were no failures.
  exit_code = 0
  return Fmt(exit_code)


def rules():
  return [
    fmt,
  ]
