# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from pants.engine.legacy.structs import (
  PantsPluginAdaptor,
  PythonAppAdaptor,
  PythonBinaryAdaptor,
  PythonTargetAdaptor,
  PythonTestsAdaptor,
  TargetAdaptor,
)
from pants.engine.rules import UnionMembership, UnionRule, rule, union
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.lint import LintResult, LintResults, LintTarget


@dataclass(frozen=True)
class LintPythonTarget:
  target: TargetAdaptor


@rule
def target_adaptor(target: PythonTargetAdaptor) -> LintPythonTarget:
  return LintPythonTarget(target)


@rule
def app_adaptor(target: PythonAppAdaptor) -> LintPythonTarget:
  return LintPythonTarget(target)


@rule
def binary_adaptor(target: PythonBinaryAdaptor) -> LintPythonTarget:
  return LintPythonTarget(target)


@rule
def tests_adaptor(target: PythonTestsAdaptor) -> LintPythonTarget:
  return LintPythonTarget(target)


@rule
def plugin_adaptor(target: PantsPluginAdaptor) -> LintPythonTarget:
  return LintPythonTarget(target)


@union
class PythonLinter:
  pass


@rule
async def lint_python_target(target: LintPythonTarget, union_membership: UnionMembership) -> LintResults:
  """This aggregator allows us to have multiple linters operate over the same Python targets.

  We do not care if linters overlap in their execution as linters have no side-effects."""
  results = await MultiGet(
    Get[LintResult](PythonLinter, member(target.target))
    for member in union_membership.union_rules[PythonLinter]
  )
  return LintResults(results)


def rules():
  return [
    lint_python_target,
    target_adaptor,
    app_adaptor,
    binary_adaptor,
    tests_adaptor,
    plugin_adaptor,
    UnionRule(LintTarget, PythonTargetAdaptor),
    UnionRule(LintTarget, PythonAppAdaptor),
    UnionRule(LintTarget, PythonBinaryAdaptor),
    UnionRule(LintTarget, PythonTestsAdaptor),
    UnionRule(LintTarget, PantsPluginAdaptor),
  ]
