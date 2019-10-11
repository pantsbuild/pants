# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.console import Console
from pants.engine.goal import Goal
from pants.engine.legacy.graph import HydratedTargets
from pants.engine.legacy.structs import (
  PythonAppAdaptor,
  PythonBinaryAdaptor,
  PythonTargetAdaptor,
  PythonTestsAdaptor,
)
from pants.engine.rules import console_rule
from pants.engine.selectors import Get
from pants.rules.core.fmt import FmtTarget


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


@console_rule
def lint(console: Console, targets: HydratedTargets) -> Lint:
  results = yield [
          Get(LintResult, FmtTarget, target.adaptor)
          for target in targets
          # @union assumes that all targets passed implement the union, so we manually
          # filter the targets we know do; this should probably no-op or log or something
          # configurable for non-matching targets.
          # We also would want to remove the workaround that filters adaptors which have a
          # `sources` attribute.
          # See https://github.com/pantsbuild/pants/issues/4535
          if isinstance(target.adaptor, (PythonAppAdaptor, PythonTargetAdaptor, PythonTestsAdaptor, PythonBinaryAdaptor)) and hasattr(target.adaptor, "sources")
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
