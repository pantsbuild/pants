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
from pants.rules.core.fmt import FormattableTarget
from pants.rules.core.lint import LintableTarget


@dataclass(frozen=True)
class FormattablePythonTarget:
  target: TargetAdaptor


@rule
def target_adaptor(target: PythonTargetAdaptor) -> FormattablePythonTarget:
  return FormattablePythonTarget(target)


@rule
def app_adaptor(target: PythonAppAdaptor) -> FormattablePythonTarget:
  return FormattablePythonTarget(target)


@rule
def binary_adaptor(target: PythonBinaryAdaptor) -> FormattablePythonTarget:
  return FormattablePythonTarget(target)


@rule
def tests_adaptor(target: PythonTestsAdaptor) -> FormattablePythonTarget:
  return FormattablePythonTarget(target)


@rule
def plugin_adaptor(target: PantsPluginAdaptor) -> FormattablePythonTarget:
  return FormattablePythonTarget(target)


def rules():
  return [
    target_adaptor,
    app_adaptor,
    binary_adaptor,
    tests_adaptor,
    plugin_adaptor,
    UnionRule(FormattableTarget, PythonTargetAdaptor),
    UnionRule(FormattableTarget, PythonAppAdaptor),
    UnionRule(FormattableTarget, PythonBinaryAdaptor),
    UnionRule(FormattableTarget, PythonTestsAdaptor),
    UnionRule(FormattableTarget, PantsPluginAdaptor),
    # NB: We assume that any formatter can also act as a linter, i.e. that they surface some flag
    # like --check. If we ever encounter a tool that is only a formatter, then we would need to
    # rename FormattablePythonTarget to FormattableAndLintablePythonTarget, then have
    # FormattablePythonTarget only register UnionRules against FormattableTarget.
    UnionRule(LintableTarget, PythonTargetAdaptor),
    UnionRule(LintableTarget, PythonAppAdaptor),
    UnionRule(LintableTarget, PythonBinaryAdaptor),
    UnionRule(LintableTarget, PythonTestsAdaptor),
    UnionRule(LintableTarget, PantsPluginAdaptor),
  ]
