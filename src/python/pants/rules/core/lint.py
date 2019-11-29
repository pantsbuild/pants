# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.console import Console
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.isolated_process import FallibleExecuteProcessResult
from pants.engine.legacy.graph import HydratedTargets
from pants.engine.rules import UnionMembership, console_rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.fmt import TargetWithSources


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


class LintOptions(GoalSubsystem):
  """Lint source code."""

  # TODO: make this "lint"
  # Blocked on https://github.com/pantsbuild/pants/issues/8351
  name = 'lint-v2'


class Lint(Goal):
  subsystem_cls = LintOptions


@console_rule
async def lint(console: Console, targets: HydratedTargets, union_membership: UnionMembership) -> Lint:
  results = await MultiGet(
    Get(LintResult, TargetWithSources, target.adaptor)
    for target in targets
    if TargetWithSources.is_formattable_and_lintable(target.adaptor, union_membership=union_membership)
  )

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
