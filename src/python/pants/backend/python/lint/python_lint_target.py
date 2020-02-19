# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass

from pants.engine.legacy.structs import (
  PantsPluginAdaptorWithOrigin,
  PythonAppAdaptorWithOrigin,
  PythonBinaryAdaptorWithOrigin,
  PythonTargetAdaptorWithOrigin,
  PythonTestsAdaptorWithOrigin,
  TargetAdaptorWithOrigin,
)
from pants.engine.objects import union
from pants.engine.rules import RootRule, UnionMembership, UnionRule, rule
from pants.engine.selectors import Get, MultiGet
from pants.rules.core.lint import LintResult, LintResults, LintTarget


@union
class PythonLintTarget:
  pass


@dataclass(frozen=True)
class _ConcretePythonLintTarget:
  adaptor_with_origin: TargetAdaptorWithOrigin


@rule
async def lint_python_target(
  concrete_target: _ConcretePythonLintTarget, union_membership: UnionMembership,
) -> LintResults:
  """This aggregator allows us to have multiple linters operate over the same Python targets.

  We do not care if linters overlap in their execution as linters have no side-effects.
  """
  results = await MultiGet(
    Get[LintResult](PythonLintTarget, member(concrete_target.adaptor_with_origin))
    for member in union_membership.union_rules[PythonLintTarget]
  )
  return LintResults(results)


PYTHON_TARGET_TYPES = [
  PythonAppAdaptorWithOrigin,
  PythonBinaryAdaptorWithOrigin,
  PythonTargetAdaptorWithOrigin,
  PythonTestsAdaptorWithOrigin,
  PantsPluginAdaptorWithOrigin,
]


@rule
def target_adaptor(adaptor_with_origin: PythonTargetAdaptorWithOrigin) -> _ConcretePythonLintTarget:
  return _ConcretePythonLintTarget(adaptor_with_origin)


@rule
def app_adaptor(adaptor_with_origin: PythonAppAdaptorWithOrigin) -> _ConcretePythonLintTarget:
  return _ConcretePythonLintTarget(adaptor_with_origin)


@rule
def binary_adaptor(adaptor_with_origin: PythonBinaryAdaptorWithOrigin) -> _ConcretePythonLintTarget:
  return _ConcretePythonLintTarget(adaptor_with_origin)


@rule
def tests_adaptor(adaptor_with_origin: PythonTestsAdaptorWithOrigin) -> _ConcretePythonLintTarget:
  return _ConcretePythonLintTarget(adaptor_with_origin)


@rule
def plugin_adaptor(adaptor_with_origin: PantsPluginAdaptorWithOrigin) -> _ConcretePythonLintTarget:
  return _ConcretePythonLintTarget(adaptor_with_origin)


def rules():
  return [
    lint_python_target,
    target_adaptor,
    app_adaptor,
    binary_adaptor,
    tests_adaptor,
    plugin_adaptor,
    *(RootRule(target_type) for target_type in PYTHON_TARGET_TYPES),
    *(UnionRule(LintTarget, target_type) for target_type in PYTHON_TARGET_TYPES)
  ]
