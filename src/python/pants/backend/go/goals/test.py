# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from pants.backend.go.target_types import GoPackageSources
from pants.core.goals.test import TestDebugRequest, TestFieldSet, TestResult
from pants.engine.rules import collect_rules, rule
from pants.engine.unions import UnionRule


class GoTestFieldSet(TestFieldSet):
    required_fields = (GoPackageSources,)
    sources: GoPackageSources


@rule
async def run_go_tests(field_set: GoTestFieldSet) -> TestResult:
    raise NotImplementedError("This is a stub.")


@rule
async def generate_go_tests_debug_request(field_set: GoTestFieldSet) -> TestDebugRequest:
    raise NotImplementedError("This is a stub.")


def rules():
    return [
        *collect_rules(),
        UnionRule(TestFieldSet, GoTestFieldSet),
    ]
