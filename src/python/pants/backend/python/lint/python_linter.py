# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from abc import ABCMeta
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
from pants.rules.core.lint import Linter, LintResult, LintResults, LintTarget


@union
@dataclass(frozen=True)
class PythonLintTarget:
    adaptor_with_origin: TargetAdaptorWithOrigin


@dataclass(frozen=True)
class PythonLinter(Linter, metaclass=ABCMeta):
    pass


@rule
async def lint_python_target(
    target: PythonLintTarget, union_membership: UnionMembership
) -> LintResults:
    """This aggregator allows us to have multiple linters operate over the same Python targets.

    We do not care if linters overlap in their execution as linters have no side-effects.
    """
    results = await MultiGet(
        Get[LintResult](PythonLintTarget, linter((target.adaptor_with_origin,)))
        for linter in union_membership.union_rules[PythonLintTarget]
    )
    return LintResults(results)


PYTHON_TARGET_TYPES = (
    PythonAppAdaptorWithOrigin,
    PythonBinaryAdaptorWithOrigin,
    PythonTargetAdaptorWithOrigin,
    PythonTestsAdaptorWithOrigin,
    PantsPluginAdaptorWithOrigin,
)


@rule
def target_adaptor(adaptor_with_origin: PythonTargetAdaptorWithOrigin) -> PythonLintTarget:
    return PythonLintTarget(adaptor_with_origin)


@rule
def app_adaptor(adaptor_with_origin: PythonAppAdaptorWithOrigin) -> PythonLintTarget:
    return PythonLintTarget(adaptor_with_origin)


@rule
def binary_adaptor(adaptor_with_origin: PythonBinaryAdaptorWithOrigin) -> PythonLintTarget:
    return PythonLintTarget(adaptor_with_origin)


@rule
def tests_adaptor(adaptor_with_origin: PythonTestsAdaptorWithOrigin) -> PythonLintTarget:
    return PythonLintTarget(adaptor_with_origin)


@rule
def plugin_adaptor(adaptor_with_origin: PantsPluginAdaptorWithOrigin) -> PythonLintTarget:
    return PythonLintTarget(adaptor_with_origin)


def rules():
    return [
        lint_python_target,
        target_adaptor,
        app_adaptor,
        binary_adaptor,
        tests_adaptor,
        plugin_adaptor,
        *(RootRule(target_type) for target_type in PYTHON_TARGET_TYPES),
        *(UnionRule(LintTarget, target_type) for target_type in PYTHON_TARGET_TYPES),
    ]
