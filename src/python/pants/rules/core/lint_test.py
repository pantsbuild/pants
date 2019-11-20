# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from typing import List

from pants.engine.legacy.graph import HydratedTarget, TransitiveHydratedTargets
from pants.engine.legacy.structs import PythonTargetAdaptor
from pants.engine.rules import UnionMembership
from pants.option.option_value_container import OptionValueContainer, RankedValue
from pants.rules.core.lint import Lint, LintResult, TargetWithSources, lint
from pants.testutil.engine.util import MockConsole, MockGet, run_rule


def test_transitive_option() -> None:
  dependency = HydratedTarget(
    address="src/dep",
    adaptor=PythonTargetAdaptor(sources=(), name="dep"),
    dependencies=()
  )
  root = HydratedTarget(
    address="src/root",
    adaptor=PythonTargetAdaptor(sources=(), name="root"),
    dependencies=(dependency,)
  )
  targets = TransitiveHydratedTargets(closure=(dependency, root), roots=(root,))

  def assert_targets_linted(
    *, transitive: bool, expected_targets: List[HydratedTarget]
  ) -> None:
    console = MockConsole(use_colors=False)

    # TODO: make it more ergonomic in tests to set an @console_rules's Options when using
    #  engine.util.run_rule().
    options = OptionValueContainer()
    options.transitive = RankedValue(RankedValue.HARDCODED, transitive)

    run_rule(
      lint,
      rule_args=[
        console,
        Lint.Options(
          scope=Lint.name,
          scoped_options=options,
        ),
        targets,
        UnionMembership(union_rules={TargetWithSources: [PythonTargetAdaptor]})
      ],
      mock_gets=[
        MockGet(
          product_type=LintResult,
          subject_type=PythonTargetAdaptor,
          mock=lambda target: LintResult(
            exit_code=0,
            stdout=f"The target `{target.name}` looks good!",
            stderr="",
          ),
        ),
      ],
    )
    for target in expected_targets:
      assert (
        f"The target `{target.adaptor.name}` looks good!" in
        console.stdout.getvalue().splitlines()
      )

  assert_targets_linted(transitive=False, expected_targets=[root])
  assert_targets_linted(transitive=True, expected_targets=[dependency, root])
