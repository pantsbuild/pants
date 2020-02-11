# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from dataclasses import dataclass
from typing import List

from pants.backend.python.lint.python_lint_target import PYTHON_TARGET_TYPES
from pants.engine.legacy.structs import (
  PantsPluginAdaptor,
  PythonAppAdaptor,
  PythonBinaryAdaptor,
  PythonTargetAdaptor,
  PythonTestsAdaptor,
  TargetAdaptor,
)
from pants.engine.objects import union
from pants.engine.rules import RootRule, UnionMembership, UnionRule, rule
from pants.engine.selectors import Get
from pants.rules.core.fmt import AggregatedFmtResults, FmtResult, FormatTarget


@union
class PythonFormatTarget:
  pass


@dataclass(frozen=True)
class _ConcretePythonFormatTarget:
  target: TargetAdaptor


@rule
async def format_python_target(
  wrapped_target: _ConcretePythonFormatTarget, union_membership: UnionMembership
) -> AggregatedFmtResults:
  """This aggregator allows us to have multiple formatters safely operate over the same Python
  targets, even if they modify the same files."""
  prior_formatter_result_digest = wrapped_target.target.sources.snapshot.directory_digest
  results: List[FmtResult] = []
  for member in union_membership.union_rules[PythonFormatTarget]:
    result = await Get[FmtResult](
      PythonFormatTarget,
      member(wrapped_target.target, prior_formatter_result_digest=prior_formatter_result_digest),
    )
    results.append(result)
    prior_formatter_result_digest = result.digest
  return AggregatedFmtResults(tuple(results), combined_digest=prior_formatter_result_digest)


@rule
def target_adaptor(target: PythonTargetAdaptor) -> _ConcretePythonFormatTarget:
  return _ConcretePythonFormatTarget(target)


@rule
def app_adaptor(target: PythonAppAdaptor) -> _ConcretePythonFormatTarget:
  return _ConcretePythonFormatTarget(target)


@rule
def binary_adaptor(target: PythonBinaryAdaptor) -> _ConcretePythonFormatTarget:
  return _ConcretePythonFormatTarget(target)


@rule
def tests_adaptor(target: PythonTestsAdaptor) -> _ConcretePythonFormatTarget:
  return _ConcretePythonFormatTarget(target)


@rule
def plugin_adaptor(target: PantsPluginAdaptor) -> _ConcretePythonFormatTarget:
  return _ConcretePythonFormatTarget(target)


def rules():
  return [
    format_python_target,
    target_adaptor,
    app_adaptor,
    binary_adaptor,
    tests_adaptor,
    plugin_adaptor,
    *(RootRule(target_type) for target_type in PYTHON_TARGET_TYPES),
    *(UnionRule(FormatTarget, target_type) for target_type in PYTHON_TARGET_TYPES)
  ]
