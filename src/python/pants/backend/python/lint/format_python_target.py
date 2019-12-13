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
from pants.rules.core.fmt import FmtResult, FmtResults, FormatTarget
from pants.rules.core.lint import LintResult, LintResults, LintTarget


@union
class PythonFormatTarget:
  pass


@dataclass(frozen=True)
class ConcretePythonFormatTarget:
  target: TargetAdaptor


@rule
async def format_python_target(
  wrapped_target: ConcretePythonFormatTarget, union_membership: UnionMembership
) -> FmtResults:
  """This aggregator allows us to have multiple formatters format the same Python targets."""
  results = await MultiGet(
    Get[FmtResult](PythonFormatTarget, member(wrapped_target.target))
    for member in union_membership.union_rules[PythonFormatTarget]
  )
  return FmtResults(results)


@rule
async def lint_python_target(
  wrapped_target: ConcretePythonFormatTarget, union_membership: UnionMembership
) -> LintResults:
  """This aggregator allows us to have multiple formatters lint over the same Python targets."""
  results = await MultiGet(
    Get[LintResult](PythonFormatTarget, member(wrapped_target.target))
    for member in union_membership.union_rules[PythonFormatTarget]
  )
  return LintResults(results)


@rule
def target_adaptor(target: PythonTargetAdaptor) -> ConcretePythonFormatTarget:
  return ConcretePythonFormatTarget(target)


@rule
def app_adaptor(target: PythonAppAdaptor) -> ConcretePythonFormatTarget:
  return ConcretePythonFormatTarget(target)


@rule
def binary_adaptor(target: PythonBinaryAdaptor) -> ConcretePythonFormatTarget:
  return ConcretePythonFormatTarget(target)


@rule
def tests_adaptor(target: PythonTestsAdaptor) -> ConcretePythonFormatTarget:
  return ConcretePythonFormatTarget(target)


@rule
def plugin_adaptor(target: PantsPluginAdaptor) -> ConcretePythonFormatTarget:
  return ConcretePythonFormatTarget(target)


def rules():
  return [
    format_python_target,
    lint_python_target,
    target_adaptor,
    app_adaptor,
    binary_adaptor,
    tests_adaptor,
    plugin_adaptor,
    UnionRule(FormatTarget, PythonTargetAdaptor),
    UnionRule(FormatTarget, PythonAppAdaptor),
    UnionRule(FormatTarget, PythonBinaryAdaptor),
    UnionRule(FormatTarget, PythonTestsAdaptor),
    UnionRule(FormatTarget, PantsPluginAdaptor),
    # NB: We assume that any formatter can also act as a linter, i.e. that they surface some flag
    # like --check. If we ever encounter a tool that is only a formatter, then we would need to
    # rename PythonFormatTarget to PythonFormatAndLintTarget, then have
    # PythonFormatTarget only register UnionRules against FormatTarget.
    UnionRule(LintTarget, PythonTargetAdaptor),
    UnionRule(LintTarget, PythonAppAdaptor),
    UnionRule(LintTarget, PythonBinaryAdaptor),
    UnionRule(LintTarget, PythonTestsAdaptor),
    UnionRule(LintTarget, PantsPluginAdaptor),
  ]
