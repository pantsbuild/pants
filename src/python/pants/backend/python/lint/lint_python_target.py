# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.engine.legacy.structs import (
  PantsPluginAdaptor,
  PythonAppAdaptor,
  PythonBinaryAdaptor,
  PythonTargetAdaptor,
  PythonTestsAdaptor,
)
from pants.engine.rules import UnionMembership, UnionRule, rule, union
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.lint import LintResult, LintResults, LintTarget


@union
class LintPythonTarget:
  pass


# @rule
# def target_adaptor(target: PythonTargetAdaptor) -> LintPythonTarget:
#   return LintPythonTarget(target)
#
#
# @rule
# def app_adaptor(target: PythonAppAdaptor) -> LintPythonTarget:
#   return LintPythonTarget(target)
#
#
# @rule
# def binary_adaptor(target: PythonBinaryAdaptor) -> LintPythonTarget:
#   return LintPythonTarget(target)
#
#
# @rule
# def tests_adaptor(target: PythonTestsAdaptor) -> LintPythonTarget:
#   return LintPythonTarget(target)
#
#
# @rule
# def plugin_adaptor(target: PantsPluginAdaptor) -> LintPythonTarget:
#   return LintPythonTarget(target)


@rule
async def lint_python_target(target: LintTarget, union_membership: UnionMembership) -> LintResults:
  """This aggregator allows us to have multiple linters operate over the same Python targets.

  We do not care if linters overlap in their execution as linters have no side-effects."""
  results = await MultiGet(
    Get[LintResult](LintPythonTarget, member(target))
    for member in union_membership.union_rules[LintPythonTarget]
  )
  return LintResults(results)


def rules():
  return [
    lint_python_target,
    UnionRule(LintTarget, LintPythonTarget),
    UnionRule(LintPythonTarget, PythonTargetAdaptor),
    UnionRule(LintPythonTarget, PythonAppAdaptor),
    UnionRule(LintPythonTarget, PythonBinaryAdaptor),
    UnionRule(LintPythonTarget, PythonTestsAdaptor),
    UnionRule(LintPythonTarget, PantsPluginAdaptor),
    # target_adaptor,
    # app_adaptor,
    # binary_adaptor,
    # tests_adaptor,
    # plugin_adaptor,
    # UnionRule(LintTarget, PythonTargetAdaptor),
    # UnionRule(LintTarget, PythonAppAdaptor),
    # UnionRule(LintTarget, PythonBinaryAdaptor),
    # UnionRule(LintTarget, PythonTestsAdaptor),
    # UnionRule(LintTarget, PantsPluginAdaptor),
  ]
