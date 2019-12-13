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
  """This aggregator allows us to have multiple formatters operate over the same Python targets."""
  results = await MultiGet(
    Get[FmtResult](PythonFormatTarget, member(wrapped_target.target))
    for member in union_membership.union_rules[PythonFormatTarget]
  )
  return FmtResults(results)


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
  ]
