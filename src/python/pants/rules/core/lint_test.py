# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Callable, List, Optional, Tuple

from pants.engine.legacy.graph import HydratedTarget, HydratedTargets
from pants.engine.legacy.structs import JvmAppAdaptor, PythonTargetAdaptor
from pants.engine.rules import UnionMembership
from pants.rules.core.fmt_test import FmtTest
from pants.rules.core.lint import Lint, LintResult, LintTarget, lint
from pants.testutil.engine.util import MockConsole, MockGet, run_rule
from pants.testutil.test_base import TestBase


class LintTest(TestBase):

  @staticmethod
  def run_lint_rule(
    *,
    targets: List[HydratedTarget],
    mock_linter: Optional[Callable[[PythonTargetAdaptor], LintResult]] = None,
  ) -> Tuple[Lint, str]:
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
        UnionMembership(union_rules={LintTarget: [PythonTargetAdaptor]})
      ],
      mock_gets=[
        MockGet(product_type=LintResult, subject_type=PythonTargetAdaptor, mock=mock_linter),
      ],
    )
    return result, console.stdout.getvalue()

  def test_non_union_member_noops(self) -> None:
    result, stdout = self.run_lint_rule(
      targets=[FmtTest.make_hydrated_target(adaptor_type=JvmAppAdaptor)],
    )
    assert result.exit_code == 0
    assert stdout == ""

  def test_empty_target_noops(self) -> None:
    result, stdout = self.run_lint_rule(
      targets=[FmtTest.make_hydrated_target(adaptor_type=JvmAppAdaptor)],
    )
    assert result.exit_code == 0
    assert stdout == ""

  def test_single_target(self) -> None:
    result, stdout = self.run_lint_rule(targets=[FmtTest.make_hydrated_target()])
    assert result.exit_code == 1
    assert stdout.strip() == "Linted the target `target`"

  def test_multiple_targets(self) -> None:
    # Notably, if any single target fails, the error code should propagate to the whole run.
    def mock_linter(adaptor: PythonTargetAdaptor) -> LintResult:
      if adaptor.name == "bad":
        return LintResult(exit_code=127, stdout="failure", stderr="")
      return LintResult(exit_code=0, stdout=f"Linted the target `{adaptor.name}`", stderr="")

    result, stdout = self.run_lint_rule(
      targets=[FmtTest.make_hydrated_target(name="good"), FmtTest.make_hydrated_target(name="bad")],
      mock_linter=mock_linter,
    )
    assert result.exit_code == 127
    assert stdout.splitlines() == ["Linted the target `good`", "failure"]
