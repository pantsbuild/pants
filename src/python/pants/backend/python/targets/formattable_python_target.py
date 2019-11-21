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
from pants.rules.core.fmt import TargetWithSources


# Note: this is a workaround until https://github.com/pantsbuild/pants/issues/8343 is addressed
# We have to write this type which basically represents a union of all various kinds of targets
# containing python files so we can have one single type used as an input in the run_black rule.
@dataclass(frozen=True)
class FormattablePythonTarget:
  target: TargetAdaptor


# TODO: remove this workaround once https://github.com/pantsbuild/pants/issues/8343 is addressed
@rule
def target_adaptor(target: PythonTargetAdaptor) -> FormattablePythonTarget:
  return FormattablePythonTarget(target)


# TODO: remove this workaround once https://github.com/pantsbuild/pants/issues/8343 is addressed
@rule
def app_adaptor(target: PythonAppAdaptor) -> FormattablePythonTarget:
  return FormattablePythonTarget(target)


# TODO: remove this workaround once https://github.com/pantsbuild/pants/issues/8343 is addressed
@rule
def binary_adaptor(target: PythonBinaryAdaptor) -> FormattablePythonTarget:
  return FormattablePythonTarget(target)


# TODO: remove this workaround once https://github.com/pantsbuild/pants/issues/8343 is addressed
@rule
def tests_adaptor(target: PythonTestsAdaptor) -> FormattablePythonTarget:
  return FormattablePythonTarget(target)


# TODO: remove this workaround once https://github.com/pantsbuild/pants/issues/8343 is addressed
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
    UnionRule(TargetWithSources, PythonTargetAdaptor),
    UnionRule(TargetWithSources, PythonAppAdaptor),
    UnionRule(TargetWithSources, PythonBinaryAdaptor),
    UnionRule(TargetWithSources, PythonTestsAdaptor),
    UnionRule(TargetWithSources, PantsPluginAdaptor),
  ]
