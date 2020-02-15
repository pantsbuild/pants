# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import Callable, List, Optional, Tuple

from pants.engine.legacy.graph import HydratedTargetsWithOrigins, HydratedTargetWithOrigin
from pants.engine.legacy.structs import JvmAppAdaptor, PythonTargetAdaptorWithOrigin
from pants.engine.rules import UnionMembership
from pants.rules.core.fmt_test import FmtTest
from pants.rules.core.lint import Lint, LintResult, LintResults, LintTarget, lint
from pants.testutil.engine.util import MockConsole, MockGet, run_rule
from pants.testutil.test_base import TestBase


class LintTest(TestBase):

  @staticmethod
  def run_lint_rule(
    *,
    targets: List[HydratedTargetWithOrigin],
    mock_linters: Optional[Callable[[PythonTargetAdaptorWithOrigin], LintResults]] = None,
  ) -> Tuple[Lint, str]:
    if mock_linters is None:
      mock_linters = lambda adaptor_with_origin: LintResults([LintResult(
        exit_code=1, stdout=f"Linted `{adaptor_with_origin.adaptor.name}`", stderr=""
      )])
    console = MockConsole(use_colors=False)
    result: Lint = run_rule(
      lint,
      rule_args=[
        console,
        HydratedTargetsWithOrigins(targets),
        UnionMembership(union_rules={LintTarget: [PythonTargetAdaptorWithOrigin]})
      ],
      mock_gets=[
        MockGet(
          product_type=LintResults, subject_type=PythonTargetAdaptorWithOrigin, mock=mock_linters,
        ),
      ],
    )
    return result, console.stdout.getvalue()

  def test_non_union_member_noops(self) -> None:
    result, stdout = self.run_lint_rule(
      targets=[FmtTest.make_hydrated_target_with_origin(adaptor_type=JvmAppAdaptor)],
    )
    assert result.exit_code == 0
    assert stdout == ""

  def test_empty_target_noops(self) -> None:
    result, stdout = self.run_lint_rule(
      targets=[FmtTest.make_hydrated_target_with_origin(include_sources=False)],
    )
    assert result.exit_code == 0
    assert stdout == ""

  def test_single_target_with_one_linter(self) -> None:
    result, stdout = self.run_lint_rule(targets=[FmtTest.make_hydrated_target_with_origin()])
    assert result.exit_code == 1
    assert stdout.strip() == "Linted `target`"

  def test_single_target_with_multiple_linters(self) -> None:
    def mock_linters(_: PythonTargetAdaptorWithOrigin) -> LintResults:
      return LintResults([
        LintResult(exit_code=0, stdout=f"Linter 1", stderr=""),
        LintResult(exit_code=1, stdout=f"Linter 2", stderr=""),
      ])

    result, stdout = self.run_lint_rule(
      targets=[FmtTest.make_hydrated_target_with_origin()], mock_linters=mock_linters,
    )
    assert result.exit_code == 1
    assert stdout.splitlines() == ["Linter 1", "Linter 2"]

  def test_multiple_targets_with_one_linter(self) -> None:
    # If any single target fails, the error code should propagate to the whole run.
    def mock_linters(adaptor_with_origin: PythonTargetAdaptorWithOrigin) -> LintResults:
      name = adaptor_with_origin.adaptor.name
      if name == "bad":
        return LintResults([LintResult(exit_code=127, stdout=f"`{name}` failed", stderr="")])
      return LintResults([LintResult(exit_code=0, stdout=f"`{name}` passed", stderr="")])

    result, stdout = self.run_lint_rule(
      targets=[
        FmtTest.make_hydrated_target_with_origin(name="good"),
        FmtTest.make_hydrated_target_with_origin(name="bad"),
      ],
      mock_linters=mock_linters,
    )
    assert result.exit_code == 127
    assert stdout.splitlines() == ["`good` passed", "`bad` failed"]

  def test_multiple_targets_with_multiple_linters(self) -> None:
    def mock_linters(adaptor_with_origin: PythonTargetAdaptorWithOrigin) -> LintResults:
      name = adaptor_with_origin.adaptor.name
      if name == "bad":
        return LintResults([
          LintResult(exit_code=0, stdout=f"Linter 1 passed for `{name}`", stderr=""),
          LintResult(exit_code=127, stdout=f"Linter 2 failed for `{name}`", stderr=""),
        ])
      return LintResults([
        LintResult(exit_code=0, stdout=f"Linter 1 passed for `{name}`", stderr=""),
        LintResult(exit_code=0, stdout=f"Linter 2 passed for `{name}`", stderr=""),
      ])

    result, stdout = self.run_lint_rule(
      targets=[
        FmtTest.make_hydrated_target_with_origin(name="good"),
        FmtTest.make_hydrated_target_with_origin(name="bad"),
      ],
      mock_linters=mock_linters,
    )
    assert result.exit_code == 127
    assert stdout.splitlines() == [
      "Linter 1 passed for `good`",
      "Linter 2 passed for `good`",
      "Linter 1 passed for `bad`",
      "Linter 2 failed for `bad`",
    ]
