# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from typing import ContextManager

import pytest

from pants.backend.visibility.validate import VisibilityField, VisibilityViolationError, rules
from pants.core.target_types import rules as core_target_types_rules
from pants.core.util_rules import archive
from pants.engine.addresses import Address
from pants.engine.target import (
    COMMON_TARGET_FIELDS,
    Dependencies,
    Target,
    TransitiveTargets,
    TransitiveTargetsRequest,
)
from pants.testutil.pytest_util import no_exception
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error, logging
from pants.util.logging import LogLevel


class TestDependencies(Dependencies):
    pass


class TestTarget(Target):
    alias = "tgt"
    core_fields = (
        *COMMON_TARGET_FIELDS,
        TestDependencies,
    )

    __test__ = False


@pytest.fixture
@logging(level=LogLevel.TRACE)
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=(
            *archive.rules(),
            *core_target_types_rules(),
            *rules(),
            TestTarget.register_plugin_field(VisibilityField),
            QueryRule(TransitiveTargets, (TransitiveTargetsRequest,)),
        ),
        target_types=(TestTarget,),
    )


@pytest.mark.parametrize(
    "visibility, dependencies, expect",
    [
        pytest.param(dict(), dict(), no_exception(), id="Empty"),
        pytest.param(
            dict(a=["src/test/a::"], a_sub=["src/test/a/sub::"]),
            dict(a=["src/test/b:x"], a_sub=["src/test/a:x"]),
            no_exception(),
            id="a private ok",
        ),
        pytest.param(
            dict(a=["src/test/a::"], a_sub=["src/test/a/sub::"]),
            dict(b=["src/test/a:x"]),
            engine_error(
                VisibilityViolationError, contains="src/test/a:x has visibility: src/test/a::"
            ),
            id="a private violated",
        ),
        pytest.param(
            dict(a=["::"], a_sub=["src/test/a/sub::"]),
            dict(b=["src/test/a:x"], b_sub=["src/test/a/sub:x"]),
            engine_error(
                VisibilityViolationError,
                contains="src/test/a/sub:x has visibility: src/test/a/sub::",
            ),
            id="a sub private violated",
        ),
        pytest.param(
            dict(a=["src/test/a::"], a_sub=["src/test/b/sub/", "src/test/a/sub::"]),
            dict(a=["src/test/b:x"], b_sub=["src/test/a/sub:x"]),
            no_exception(),
            id="a private punch whole for package",
        ),
        pytest.param(
            dict(a=["src/test/a::"], a_sub=["src/test/b/sub/", "src/test/a/sub::"]),
            dict(a=["src/test/b:x"], b_subsuffix=["src/test/a/sub:x"]),
            engine_error(
                VisibilityViolationError,
                contains="src/test/a/sub:x has visibility: src/test/b/sub, src/test/a/sub::",
            ),
            id="a private punch whole for package violation",
        ),
        pytest.param(
            dict(a=[]),
            dict(a_sub=["src/test/a:x"]),
            engine_error(
                VisibilityViolationError,
                contains=" * src/test/a:x has visibility: <none>",
            ),
            id="not visible at all",
        ),
    ],
)
def test_visibility(
    rule_runner: RuleRunner, visibility: dict, dependencies: dict, expect: ContextManager
) -> None:
    def tgt(key: str) -> str:
        return f"""tgt(name="x", visibility={visibility.get(key)}, dependencies={dependencies.get(key)})"""

    rule_runner.write_files(
        {
            "src/test/a/BUILD": tgt("a"),
            "src/test/b/BUILD": tgt("b"),
            "src/test/a/sub/BUILD": tgt("a_sub"),
            "src/test/b/sub/BUILD": tgt("b_sub"),
            "src/test/b/subsuffix/BUILD": tgt("b_subsuffix"),
        }
    )

    with expect:
        roots = (
            Address(f"src/test/{path}", target_name="x")
            for path in ("a", "a/sub", "b", "b/sub", "b/subsuffix")
        )
        rule_runner.request(TransitiveTargets, (TransitiveTargetsRequest(roots),))
