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
from pants.engine.rules import UnionRule, rule
from pants.rules.core.fmt import FormatTarget
from pants.rules.core.lint import LintTarget


@dataclass(frozen=True)
class FormatPythonTarget:
  target: TargetAdaptor


@rule
def target_adaptor(target: PythonTargetAdaptor) -> FormatPythonTarget:
  return FormatPythonTarget(target)


@rule
def app_adaptor(target: PythonAppAdaptor) -> FormatPythonTarget:
  return FormatPythonTarget(target)


@rule
def binary_adaptor(target: PythonBinaryAdaptor) -> FormatPythonTarget:
  return FormatPythonTarget(target)


@rule
def tests_adaptor(target: PythonTestsAdaptor) -> FormatPythonTarget:
  return FormatPythonTarget(target)


@rule
def plugin_adaptor(target: PantsPluginAdaptor) -> FormatPythonTarget:
  return FormatPythonTarget(target)


def rules():
  return [
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
    # rename FormatPythonTarget to FormattableAndLintablePythonTarget, then have
    # FormatPythonTarget only register UnionRules against FormatTarget.
    UnionRule(LintTarget, PythonTargetAdaptor),
    UnionRule(LintTarget, PythonAppAdaptor),
    UnionRule(LintTarget, PythonBinaryAdaptor),
    UnionRule(LintTarget, PythonTestsAdaptor),
    UnionRule(LintTarget, PantsPluginAdaptor),
  ]
