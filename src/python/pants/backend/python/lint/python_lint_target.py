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


@union
class PythonLintTarget:
  pass


@dataclass(frozen=True)
class _ConcretePythonLintTarget:
  target: TargetAdaptor


@rule
async def lint_python_target(
  wrapped_target: _ConcretePythonLintTarget, union_membership: UnionMembership
) -> LintResults:
  """This aggregator allows us to have multiple linters operate over the same Python targets.

  We do not care if linters overlap in their execution as linters have no side-effects."""
  results = await MultiGet(
    Get[LintResult](PythonLintTarget, member(wrapped_target.target))
    for member in union_membership.union_rules[PythonLintTarget]
  )
  return LintResults(results)


@rule
def target_adaptor(target: PythonTargetAdaptor) -> _ConcretePythonLintTarget:
  return _ConcretePythonLintTarget(target)


@rule
def app_adaptor(target: PythonAppAdaptor) -> _ConcretePythonLintTarget:
  return _ConcretePythonLintTarget(target)


@rule
def binary_adaptor(target: PythonBinaryAdaptor) -> _ConcretePythonLintTarget:
  return _ConcretePythonLintTarget(target)


@rule
def tests_adaptor(target: PythonTestsAdaptor) -> _ConcretePythonLintTarget:
  return _ConcretePythonLintTarget(target)


@rule
def plugin_adaptor(target: PantsPluginAdaptor) -> _ConcretePythonLintTarget:
  return _ConcretePythonLintTarget(target)


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
