# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import FallibleExecuteProcessResult
from pants.engine.legacy.graph import HydratedTargets
from pants.engine.legacy.structs import TargetAdaptor
from pants.engine.objects import Collection
from pants.engine.rules import UnionMembership, console_rule, union
from pants.engine.selectors import Get, MultiGet


@dataclass(frozen=True)
class LintResult:
  exit_code: int
  stdout: str
  stderr: str

  @staticmethod
  def from_fallible_execute_process_result(
    process_result: FallibleExecuteProcessResult
  ) -> "LintResult":
    return LintResult(
      exit_code=process_result.exit_code,
      stdout=process_result.stdout.decode(),
      stderr=process_result.stderr.decode(),
    )


class LintResults(Collection[LintResult]):
  """This collection allows us to aggregate multiple `LintResult`s for a language."""


@union
class LintTarget:
  """A union for registration of a formattable target type."""

  @staticmethod
  def is_lintable(
    target_adaptor: TargetAdaptor, *, union_membership: UnionMembership
  ) -> bool:
    return (
      union_membership.is_member(LintTarget, target_adaptor)
      # TODO: make TargetAdaptor return a 'sources' field with an empty snapshot instead of
      #  raising to remove the hasattr() checks here!
      and hasattr(target_adaptor, "sources")
      and target_adaptor.sources.snapshot.files  # i.e., sources is not empty
    )


class LintOptions(GoalSubsystem):
  """Lint source code."""

  # TODO: make this "lint"
  # Blocked on https://github.com/pantsbuild/pants/issues/8351
  name = 'lint2'


class Lint(Goal):
  subsystem_cls = LintOptions


@console_rule
async def lint(console: Console, targets: HydratedTargets, union_membership: UnionMembership) -> Lint:
  nested_results = await MultiGet(
    Get[LintResults](LintTarget, target.adaptor)
    for target in targets
    if LintTarget.is_lintable(target.adaptor, union_membership=union_membership)
  )
  results = [result for results in nested_results for result in results]

  if not results:
    return Lint(exit_code=0)

  exit_code = 0
  for result in results:
    if result.stdout:
      console.print_stdout(result.stdout)
    if result.stderr:
      console.print_stderr(result.stderr)
    if result.exit_code != 0:
      exit_code = result.exit_code

  return Lint(exit_code)


def rules():
  return [
    lint,
  ]
