# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
from pathlib import PurePath
from textwrap import dedent
from typing import Any

import pytest

from pants.backend.visibility.rule_types import (
    BuildFileVisibilityRules,
    BuildFileVisibilityRulesError,
    VisibilityRule,
    VisibilityRuleSet,
    flatten,
)
from pants.backend.visibility.rules import rules as visibility_rules
from pants.core.target_types import FilesGeneratorTarget, GenericTarget, ResourcesGeneratorTarget
from pants.engine.addresses import Address, Addresses, AddressInput
from pants.engine.internals.dep_rules import DependencyRuleAction, DependencyRuleActionDeniedError
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.target import DependenciesRuleAction, DependenciesRuleActionRequest
from pants.testutil.pytest_util import assert_logged, no_exception
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error

# -----------------------------------------------------------------------------------------------
# Rule type classes tests.
# -----------------------------------------------------------------------------------------------


def parse_rule(rule: str, relpath: str = "test/path") -> VisibilityRule:
    return VisibilityRule.parse(rule, relpath)


def parse_ruleset(rules: Any, relpath: str = "test/path") -> VisibilityRuleSet:
    return VisibilityRuleSet.parse(rules, relpath)


@pytest.mark.parametrize(
    "expected, xs",
    [
        (
            ["foo"],
            "foo",
        ),
        (
            ["foo", "bar"],
            ("foo", "bar"),
        ),
        (
            ["foo", "bar", "baz"],
            (
                "foo",
                (
                    "bar",
                    ("baz",),
                ),
            ),
        ),
        (
            ["foo", "bar", "baz"],
            (
                "foo",
                (
                    "bar",
                    "baz",
                ),
            ),
        ),
        (
            ["foo", "bar", "baz"],
            (
                (
                    "foo",
                    "bar",
                    "baz",
                ),
            ),
        ),
        (
            ["src/test"],
            PurePath("src/test"),
        ),
    ],
)
def test_flatten(expected, xs) -> None:
    assert expected == list(flatten(xs))


@pytest.mark.parametrize(
    "rule, expected",
    [
        ("", (".",)),
        (".", (".",)),
        ("./", (".",)),
        (".foo", (".foo",)),
        ("./foo", ("./foo",)),
        ("src/foo", ("src/foo",)),
        ("src/*", ("src/*",)),
        (":", ("test/path",)),
        (":/", ("test/path",)),
        (":/*", ("test/path/*",)),
        (":/sub", ("test/path/sub",)),
        (
            "src/::",
            (
                "src",
                "src/*",
            ),
        ),
        (
            "src::",
            (
                "src",
                "src/*",
            ),
        ),
        (
            ":/::",
            (
                "test/path",
                "test/path/*",
            ),
        ),
        ("src/a/../b", ("src/b",)),
        ("src/a//b", ("src/a/b",)),
        # Test oddities..
        (":foo", (":foo",)),
        ("::foo", ("::foo",)),
        ("::/foo", ("::/foo",)),
        ("src:foo", ("src:foo",)),
        ("src/foo:", ("src/foo:",)),
        ("src::foo", ("src::foo",)),
        ("src/:foo", ("src/:foo",)),
        ("src/::foo", ("src/::foo",)),
        (
            ":/su:b::",
            (
                "test/path/su:b",
                "test/path/su:b/*",
            ),
        ),
    ],
)
def test_visibility_rule_patterns(rule: str, expected: tuple[str, ...]) -> None:
    assert expected == parse_rule(rule).patterns


@pytest.mark.parametrize(
    "expected, rule, path, relpath",
    [
        (True, "src/a", "src/a", ""),
        (True, "?src/a", "src/a", ""),
        (True, "!src/a", "src/a", ""),
        (False, "src/a", "src/b", ""),
        (False, "?src/a", "src/b", ""),
        (False, "!src/a", "src/b", ""),
        (True, "src/a/*", "src/a/b", ""),
        (True, "src/a/*", "src/a/b/c/d", ""),
        (False, "src/a/*/c", "src/a/b/c/d", ""),
        (True, "src/a/*/c", "src/a/b/d/c", ""),
        (True, ".", "src/a", "src/a"),
        (False, ".", "src/a", "src/b"),
        (False, ".", "src/a/b", "src/a"),
        (True, "./*", "src/a/b", "src/a"),
        (False, "./*", "src/a/b", "src/a/b/c"),
    ],
)
def test_visibility_rule_match(expected: bool, rule: str, path: str, relpath: str) -> None:
    assert parse_rule(rule).match(path, relpath) == expected


@pytest.mark.parametrize(
    "expected, arg",
    [
        (
            VisibilityRuleSet(
                ("target",),
                (parse_rule("src/*"),),
            ),
            ("target", "src/*"),
        ),
        (
            VisibilityRuleSet(
                ("files", "resources"),
                (
                    parse_rule(
                        "src/*",
                    ),
                    parse_rule("res/*"),
                    parse_rule("!*"),
                ),
            ),
            (("files", "resources"), "src/*", "res/*", "!*"),
        ),
    ],
)
def test_visibility_rule_set_parse(expected: VisibilityRuleSet, arg: Any) -> None:
    rule_set = parse_ruleset(arg)
    assert expected == rule_set


@pytest.mark.parametrize(
    "expected, target, rule_spec",
    [
        (
            True,
            "python_sources",
            ("python_*", ""),
        ),
        (
            False,
            "shell_sources",
            ("python_*", ""),
        ),
        (
            True,
            "files",
            (("files", "resources"), ""),
        ),
        (
            True,
            "resources",
            (("files", "resources"), ""),
        ),
        (
            False,
            "resource",
            (("files", "resources"), ""),
        ),
    ],
)
def test_visibility_rule_set_match(expected: bool, target: str, rule_spec: tuple) -> None:
    assert expected == parse_ruleset(rule_spec).match(TargetAdaptor(target, None))


@pytest.fixture
def dependencies_rules() -> BuildFileVisibilityRules:
    return BuildFileVisibilityRules(
        "test/BUILD",
        # Rules for outgoing dependency.
        (parse_ruleset(("*", ("tgt/ok/*", "?tgt/dubious/*", "!tgt/blocked/*"))),),
    )


@pytest.fixture
def dependents_rules() -> BuildFileVisibilityRules:
    return BuildFileVisibilityRules(
        "test/BUILD",
        # Rules for outgoing dependency.
        (parse_ruleset(("*", ("src/ok/*", "?src/dubious/*", "!src/blocked/*"))),),
    )


@pytest.mark.parametrize(
    "source_path, target_path, expected_action",
    [
        ("src/ok/a", "tgt/ok/b", "allow"),
        ("src/ok/a", "tgt/dubious/b", "warn"),
        ("src/ok/a", "tgt/blocked/b", "deny"),
        ("src/dubious/a", "tgt/ok/b", "warn"),
        ("src/dubious/a", "tgt/dubious/b", "warn"),
        ("src/dubious/a", "tgt/blocked/b", "deny"),
        ("src/blocked/a", "tgt/ok/b", "deny"),
        ("src/blocked/a", "tgt/dubious/b", "deny"),
        ("src/blocked/a", "tgt/blocked/b", "deny"),
    ],
)
def test_check_dependency_rules(
    dependencies_rules: BuildFileVisibilityRules,
    dependents_rules: BuildFileVisibilityRules,
    source_path: str,
    target_path: str,
    expected_action: str,
) -> None:
    assert BuildFileVisibilityRules.check_dependency_rules(
        source_adaptor=TargetAdaptor("dependent_target", "source"),
        source_path=source_path,
        dependencies_rules=dependencies_rules,
        target_adaptor=TargetAdaptor("dependency_target", "target"),
        target_path=target_path,
        dependents_rules=dependents_rules,
    ) == DependencyRuleAction(expected_action)


# -----------------------------------------------------------------------------------------------
# BUILD file level tests.
# -----------------------------------------------------------------------------------------------


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *visibility_rules(),
            QueryRule(DependenciesRuleAction, (DependenciesRuleActionRequest,)),
        ],
        target_types=[FilesGeneratorTarget, GenericTarget, ResourcesGeneratorTarget],
    )


def denied():
    return pytest.raises(
        DependencyRuleActionDeniedError,
        match="Dependency rule violation for src/origin:origin on src/dependency:dependency",
    )


@pytest.mark.parametrize(
    "rules, expect_error",
    [
        (["*"], None),
        (["!*"], denied()),
        (["src/origin", "!*"], None),
        (["!src/origin", "*"], denied()),
        (["!src/origin/nested", "*"], None),
        (["src/origin/nested", "!*"], denied()),
        (["!src/a", "!src/b", "!src/origin", "!src/c", "*"], denied()),
        (["!src/a", "!src/b", "!src/c", "*"], None),
        (["src/a", "src/b", "src/origin", "src/c", "!*"], None),
        (["src/a", "src/b", "src/c", "!*"], denied()),
    ],
)
def test_dependents_rules(rule_runner: RuleRunner, rules: list[str], expect_error) -> None:
    rule_runner.write_files(
        {
            "src/dependency/BUILD": dedent(
                f"""\
                __dependents_rules__((target, {rules}))
                target()
                """
            ),
            "src/origin/BUILD": dedent(
                """\
                target(dependencies=["src/dependency:tgt"])
                """
            ),
        },
    )

    rsp = rule_runner.request(
        DependenciesRuleAction,
        [
            DependenciesRuleActionRequest(
                Address("src/origin"),
                dependencies=Addresses([Address("src/dependency")]),
                description_of_origin="test",
            )
        ],
    )
    with expect_error or no_exception():
        rsp.execute_actions()


@pytest.mark.parametrize(
    "rules, expect_error",
    [
        (["*"], None),
        (["src/dependency", "!*"], None),
        (["src/dependency/nested", "!*"], denied()),
        (["src/*", "!*"], None),
        (["!src/*", "*"], denied()),
    ],
)
def test_dependencies_rules(rule_runner: RuleRunner, rules: list[str], expect_error) -> None:
    rule_runner.write_files(
        {
            "src/dependency/BUILD": "target()",
            "src/origin/BUILD": dedent(
                f"""\
                __dependencies_rules__((target, {rules}))
                target(dependencies=["src/dependency:tgt"])
                """
            ),
        },
    )

    rsp = rule_runner.request(
        DependenciesRuleAction,
        [
            DependenciesRuleActionRequest(
                Address("src/origin"),
                dependencies=Addresses([Address("src/dependency")]),
                description_of_origin="test",
            )
        ],
    )
    with expect_error or no_exception():
        rsp.execute_actions()


def assert_dependency_rules(
    rule_runner: RuleRunner, origin: str, *dependencies: tuple[str, DependencyRuleAction]
) -> None:
    desc = repr("assert_dependency_rules")
    source = AddressInput.parse(origin, description_of_origin=desc).dir_to_address()
    addresses = Addresses(
        [
            AddressInput.parse(
                dep, relative_to=source.spec_path, description_of_origin=desc
            ).dir_to_address()
            for dep, _ in dependencies
        ]
    )
    rsp = rule_runner.request(
        DependenciesRuleAction,
        [
            DependenciesRuleActionRequest(
                source,
                dependencies=addresses,
                description_of_origin=desc,
            )
        ],
    )

    expected = {address: action for address, (_, action) in zip(addresses, dependencies)}
    assert expected == dict(rsp.dependencies_rule)


def test_dependency_rules(rule_runner: RuleRunner, caplog) -> None:
    ROOT_BUILD = dedent(
        """
        # ROOT RULES
        #
        # Parent rules apply to whole subtree unless overridden in a child BUILD file.

        __dependencies_rules__(
          # Deny internal resources from depending on outside files.
          (resources, ".", "!*"),

          # Allow files to use anything.
          (files, "*"),

          # Allow all by default, with a warning
          ("*", "?*"),

          # Ignore (accept) empty values as no-op
          None,
          (),
        )

        __dependents_rules__(
          # Deny outside access to "private" resources.
          (resources, ".", "!*"),

          # Anyone may depend on `files` targets.
          ("files", "*"),

          # Allow all by default, with a warning
          ("*", "?*"),
        )
        """
    )

    def BUILD(dependencies: tuple = (), dependents: tuple = (), extra: str = "") -> str:
        return dedent(
            f"""
            # `files` are "public"
            files()

            # `resources` are "private"
            resources(name="internal")

            {extra}

            __dependencies_rules__(
              *{dependencies},
              extend=True,
            )

            __dependents_rules__(
              *{dependents},
              extend=True,
            )
            """
        )

    rule_runner.write_files(
        {
            "src/BUILD": ROOT_BUILD,
            "src/a/BUILD": BUILD(),
            "src/a/a2/BUILD": BUILD(
                extra="""target(name="joker")""",
            ),
            "src/b/BUILD": BUILD(
                dependents=(),
            ),
            "src/b/b2/BUILD": BUILD(
                dependents=(
                    # Override default, any target in `b` may depend on internal targets
                    ("resources", "src/b", "src/b/*", "!*"),
                    # Only `b` may depend on our nested modules.
                    ("*", "src/b/*", "!*"),
                ),
            ),
        },
    )

    allowed = DependencyRuleAction.ALLOW
    denied = DependencyRuleAction.DENY
    warned = DependencyRuleAction.WARN
    caplog.set_level(logging.DEBUG)

    assert_dependency_rules(
        rule_runner,
        "src/a",
        ("src/a:internal", allowed),
        ("src/a/a2:internal", denied),
        ("src/b", allowed),
        ("src/b:internal", denied),
        ("src/b/b2", denied),
        ("src/a/a2:joker", warned),
    )
    assert_logged(
        caplog,
        expect_logged=[
            (
                logging.DEBUG,
                "WARN: dependency on the `target` target src/a/a2:joker from a target at src/a by "
                "dependent rule '?*' declared in src/a/a2/BUILD",
            ),
        ],
        exclusively=False,
    )

    caplog.clear()
    assert_dependency_rules(
        rule_runner,
        "src/b",
        ("src/b:internal", allowed),
        ("src/b/b2:internal", allowed),
        ("src/a", allowed),
        ("src/a:internal", denied),
        ("src/a/a2", allowed),
    )
    assert_logged(
        caplog,
        expect_logged=[
            (
                logging.DEBUG,
                "DENY: dependency on the `resources` target src/a:internal from a target at src/b "
                "by dependent rule '!*' declared in src/a/BUILD",
            ),
        ],
        exclusively=False,
    )

    caplog.clear()
    assert_dependency_rules(
        rule_runner,
        "src/a:internal",
        ("src/a", allowed),
        ("src/b", denied),
    )
    assert_logged(
        caplog,
        expect_logged=[
            (
                logging.DEBUG,
                # This message is different, as it fired from a dependency rule, rather than a
                # dependent rule as in the other cases.
                "DENY: the `resources` target src/a:internal dependency to a target at src/b by "
                "dependency rule '!*' declared in src/a/BUILD",
            ),
        ],
        exclusively=False,
    )


def test_missing_rule_error_message(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """
                __dependencies_rules__(
                  (target, ".", "!*"),
                )

                __dependents_rules__(
                  (resources, "res/*"),
                )

                resources(name="res")
                target(name="tgt")
                """
            ),
        },
    )

    msg = (
        "There is no matching dependencies rule for the `resources` target src:res for the "
        "dependency on the `target` target src:tgt in src/BUILD"
    )
    with engine_error(BuildFileVisibilityRulesError, contains=msg):
        rule_runner.request(
            DependenciesRuleAction,
            [
                DependenciesRuleActionRequest(
                    Address("src", target_name="res"),
                    dependencies=Addresses([Address("src", target_name="tgt")]),
                    description_of_origin=repr("test"),
                )
            ],
        )

    msg = (
        "There is no matching dependents rule for the `resources` target src:res for the "
        "dependency from the `target` target src:tgt in src/BUILD"
    )
    with engine_error(BuildFileVisibilityRulesError, contains=msg):
        rule_runner.request(
            DependenciesRuleAction,
            [
                DependenciesRuleActionRequest(
                    Address("src", target_name="tgt"),
                    dependencies=Addresses([Address("src", target_name="res")]),
                    description_of_origin=repr("test"),
                )
            ],
        )
