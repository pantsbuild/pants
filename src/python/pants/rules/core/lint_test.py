# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Callable, List, Tuple, Type

from pants.engine.legacy.graph import HydratedTarget, HydratedTargets
from pants.engine.legacy.structs import JvmAppAdaptor, PythonTargetAdaptor, TargetAdaptor
from pants.engine.rules import UnionMembership
from pants.rules.core.lint import Lint, LintResult, TargetWithSources, lint
from pants.testutil.engine.util import MockConsole, MockGet, run_rule


def make_target(
  *, name: str = "target", adaptor_type: Type[TargetAdaptor] = PythonTargetAdaptor
) -> HydratedTarget:
  return HydratedTarget(
    address=f"src/{name}",
    adaptor=adaptor_type(sources=(), name=name),
    dependencies=()
  )


def run_lint_rule(
  *,
  targets: List[HydratedTarget],
  mock_linter: Callable[[PythonTargetAdaptor], LintResult],
) -> Tuple[Lint, MockConsole]:
  console = MockConsole(use_colors=False)
  result: Lint = run_rule(
    lint,
    rule_args=[
      console,
      HydratedTargets(targets),
      UnionMembership(union_rules={TargetWithSources: [PythonTargetAdaptor]})
    ],
    mock_gets=[
      MockGet(product_type=LintResult, subject_type=PythonTargetAdaptor, mock=mock_linter),
    ],
  )
  return result, console


def test_non_union_member_noops() -> None:
  result, console = run_lint_rule(
    targets=[make_target(adaptor_type=JvmAppAdaptor)],
    mock_linter=lambda target: LintResult(exit_code=1, stdout="", stderr=""),
  )
  assert result.exit_code == 0
  assert console.stdout.getvalue().strip() == ""


def test_failure_for_a_single_target_propagates():
  def mock_linter(adaptor: PythonTargetAdaptor) -> LintResult:
    if adaptor.name == "bad":
      return LintResult(exit_code=127, stdout="failure", stderr="failure")
    return LintResult(exit_code=0, stdout=f"Linted the target `{adaptor.name}`", stderr="..")

  result, console = run_lint_rule(
    targets=[make_target(name="good"), make_target(name="bad")], mock_linter=mock_linter,
  )
  assert result.exit_code == 127
  assert console.stdout.getvalue().splitlines() == ["Linted the target `good`", "failure"]
  assert console.stderr.getvalue().splitlines() == ["..", "failure"]
