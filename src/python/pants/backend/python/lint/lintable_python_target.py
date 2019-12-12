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
from pants.rules.core.lint import LintableTarget


@dataclass(frozen=True)
class LintablePythonTarget:
  target: TargetAdaptor


@rule
def target_adaptor(target: PythonTargetAdaptor) -> LintablePythonTarget:
  return LintablePythonTarget(target)


@rule
def app_adaptor(target: PythonAppAdaptor) -> LintablePythonTarget:
  return LintablePythonTarget(target)


@rule
def binary_adaptor(target: PythonBinaryAdaptor) -> LintablePythonTarget:
  return LintablePythonTarget(target)


@rule
def tests_adaptor(target: PythonTestsAdaptor) -> LintablePythonTarget:
  return LintablePythonTarget(target)


@rule
def plugin_adaptor(target: PantsPluginAdaptor) -> LintablePythonTarget:
  return LintablePythonTarget(target)


def rules():
  return [
    target_adaptor,
    app_adaptor,
    binary_adaptor,
    tests_adaptor,
    plugin_adaptor,
    UnionRule(LintableTarget, PythonTargetAdaptor),
    UnionRule(LintableTarget, PythonAppAdaptor),
    UnionRule(LintableTarget, PythonBinaryAdaptor),
    UnionRule(LintableTarget, PythonTestsAdaptor),
    UnionRule(LintableTarget, PantsPluginAdaptor),
  ]
