# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.console import Console
from pants.engine.goal import Goal
from pants.engine.legacy.graph import TransitiveHydratedTargets
from pants.engine.rules import UnionMembership, console_rule
from pants.engine.selectors import Get
from pants.rules.core.fmt import TargetWithSources


@dataclass(frozen=True)
class LintResult:
  exit_code: int
  stdout: str
  stderr: str


class Lint(Goal):
  """Lint source code."""

  # TODO: make this "lint"
  # Blocked on https://github.com/pantsbuild/pants/issues/8351
  name = 'lint-v2'

  @classmethod
  def register_options(cls, register):
    super().register_options(register)
    register('--transitive', type=bool, default=True,
             help="If false, act only on the targets directly specified on the command line. "
                  "If true, act on the transitive dependency closure of those targets.")


@console_rule
def lint(
  console: Console,
  lint_options: Lint.Options,
  transitive_targets: TransitiveHydratedTargets,
  union_membership: UnionMembership,
) -> Lint:

  transitive = lint_options.values.transitive

  targets = transitive_targets.closure if transitive else transitive_targets.roots
  results = yield [
    Get(LintResult, TargetWithSources, target.adaptor)
    for target in targets
    # TODO: make TargetAdaptor return a 'sources' field with an empty snapshot instead of
    # raising to remove the hasattr() checks here!
    if union_membership.is_member(TargetWithSources, target.adaptor) and hasattr(target.adaptor, "sources")
  ]

  exit_code = 0
  for result in results:
    if result.stdout:
      console.print_stdout(result.stdout)
    if result.stderr:
      console.print_stderr(result.stderr)
    if result.exit_code != 0:
      exit_code = result.exit_code

  yield Lint(exit_code)


def rules():
  return [
    lint,
  ]
