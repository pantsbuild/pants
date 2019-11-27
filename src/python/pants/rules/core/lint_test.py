# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Callable, List, Optional, Tuple, Type

from pants.engine.legacy.graph import HydratedTarget, HydratedTargets
from pants.engine.legacy.structs import JvmAppAdaptor, PythonTargetAdaptor, TargetAdaptor
from pants.engine.rules import UnionMembership
from pants.rules.core.lint import Lint, LintResult, TargetWithSources, lint
from pants.testutil.engine.util import MockConsole, MockGet, run_rule
from pants.testutil.test_base import TestBase


class LintTest(TestBase):

  @staticmethod
  def make_hydrated_target(
    *, name: str = "target", adaptor_type: Type[TargetAdaptor] = PythonTargetAdaptor
  ) -> HydratedTarget:
    return HydratedTarget(
      address=f"src/{name}",
      adaptor=adaptor_type(sources=(), name=name),
      dependencies=()
    )

  @staticmethod
  def run_lint_rule(
    *,
    targets: List[HydratedTarget],
    mock_linter: Optional[Callable[[PythonTargetAdaptor], LintResult]] = None,
  ) -> Tuple[Lint, MockConsole]:
    if mock_linter is None:
      mock_linter = lambda target_adaptor: LintResult(
        exit_code=1, stdout=f"Linted the target `{target_adaptor.name}`", stderr=""
      )
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

  def test_non_union_member_noops(self) -> None:
    result, console = self.run_lint_rule(
      targets=[self.make_hydrated_target(adaptor_type=JvmAppAdaptor)],
    )
    assert result.exit_code == 0
    assert console.stdout.getvalue().strip() == ""

  def test_single_target(self) -> None:
    result, console = self.run_lint_rule(targets=[self.make_hydrated_target()])
    assert result.exit_code == 1
    assert console.stdout.getvalue().strip() == "Linted the target `target`"

  def test_multiple_targets(self) -> None:
    # Notably, if any single target fails, the error code should propagate to the whole run.
    def mock_linter(adaptor: PythonTargetAdaptor) -> LintResult:
      if adaptor.name == "bad":
        return LintResult(exit_code=127, stdout="failure", stderr="failure")
      return LintResult(exit_code=0, stdout=f"Linted the target `{adaptor.name}`", stderr="..")

    result, console = self.run_lint_rule(
      targets=[self.make_hydrated_target(name="good"), self.make_hydrated_target(name="bad")],
      mock_linter=mock_linter,
    )
    assert result.exit_code == 127
    assert console.stdout.getvalue().splitlines() == ["Linted the target `good`", "failure"]
    assert console.stderr.getvalue().splitlines() == ["..", "failure"]
