# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import logging
import re
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
from pants.engine.internals.dep_rules import (
    DependencyRuleAction,
    DependencyRuleActionDeniedError,
    DependencyRuleApplication,
)
from pants.engine.internals.target_adaptor import TargetAdaptor
from pants.engine.target import DependenciesRuleApplication, DependenciesRuleApplicationRequest
from pants.testutil.pytest_util import assert_logged, no_exception
from pants.testutil.rule_runner import QueryRule, RuleRunner, engine_error
from pants.util.strutil import softwrap

# -----------------------------------------------------------------------------------------------
# Rule type classes tests.
# -----------------------------------------------------------------------------------------------


def parse_rule(rule: str, relpath: str = "test/path") -> VisibilityRule:
    return VisibilityRule.parse(rule, relpath)


def parse_ruleset(rules: Any, build_file: str = "test/path/BUILD") -> VisibilityRuleSet:
    return VisibilityRuleSet.parse(build_file, rules)


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
        (
            ["src/test", "", "# comment", "last/rule", ""],
            """\
            src/test

            # comment
            last/rule
            """,
        ),
    ],
)
def test_flatten(expected, xs) -> None:
    assert expected == list(flatten(xs))


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
        (False, "src/a/*", "src/a/b/c/d", ""),
        (True, "src/a/**", "src/a/b/c/d", ""),
        (True, "src/a/**", "src/a", ""),
        (False, "src/a/*", "src/a", ""),
        (False, "src/a/*/c", "src/a/b/c/d", ""),
        (True, "src/a/**/c", "src/a/b/d/c", ""),
        (True, ".", "src/a", "src/a"),
        (False, ".", "src/a", "src/b"),
        (False, ".", "src/a/b", "src/a"),
        (True, "./*", "src/a/b", "src/a"),
        (False, "./*", "src/a/b", "src/a/b/c"),
    ],
)
def test_visibility_rule(expected: bool, rule: str, path: str, relpath: str) -> None:
    assert parse_rule(rule).match(path, relpath) == expected


@pytest.mark.parametrize(
    "expected, arg",
    [
        (
            VisibilityRuleSet(
                "test/path/BUILD",
                ("target",),
                (parse_rule("src/*"),),
            ),
            ("target", "src/*"),
        ),
        (
            VisibilityRuleSet(
                "test/path/BUILD",
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
        "a/BUILD",
        # Rules for outgoing dependency.
        (parse_ruleset(("*", ("tgt/ok/*", "?tgt/dubious/*", "!tgt/blocked/*")), "a/BUILD"),),
    )


@pytest.fixture
def dependents_rules() -> BuildFileVisibilityRules:
    return BuildFileVisibilityRules(
        "b/BUILD",
        # Rules for outgoing dependency.
        (parse_ruleset(("*", ("src/ok/*", "?src/dubious/*", "!src/blocked/*")), "b/BUILD"),),
    )


@pytest.mark.parametrize(
    "source_path, target_path, expected_action, expected_rule",
    [
        ("src/ok/a", "tgt/ok/b", "allow", "a/BUILD[tgt/ok/*] -> b/BUILD[src/ok/*]"),
        ("src/ok/a", "tgt/dubious/b", "warn", "a/BUILD[?tgt/dubious/*] -> b/BUILD[src/ok/*]"),
        ("src/ok/a", "tgt/blocked/b", "deny", "a/BUILD[!tgt/blocked/*] -> b/BUILD[src/ok/*]"),
        ("src/dubious/a", "tgt/ok/b", "warn", "a/BUILD[tgt/ok/*] -> b/BUILD[?src/dubious/*]"),
        (
            "src/dubious/a",
            "tgt/dubious/b",
            "warn",
            "a/BUILD[?tgt/dubious/*] -> b/BUILD[?src/dubious/*]",
        ),
        (
            "src/dubious/a",
            "tgt/blocked/b",
            "deny",
            "a/BUILD[!tgt/blocked/*] -> b/BUILD[?src/dubious/*]",
        ),
        ("src/blocked/a", "tgt/ok/b", "deny", "a/BUILD[tgt/ok/*] -> b/BUILD[!src/blocked/*]"),
        (
            "src/blocked/a",
            "tgt/dubious/b",
            "deny",
            "a/BUILD[?tgt/dubious/*] -> b/BUILD[!src/blocked/*]",
        ),
        (
            "src/blocked/a",
            "tgt/blocked/b",
            "deny",
            "a/BUILD[!tgt/blocked/*] -> b/BUILD[!src/blocked/*]",
        ),
    ],
)
def test_check_dependency_rules(
    dependencies_rules: BuildFileVisibilityRules,
    dependents_rules: BuildFileVisibilityRules,
    source_path: str,
    target_path: str,
    expected_action: str,
    expected_rule: str,
) -> None:
    origin_address = Address(source_path, target_name="source")
    dependency_address = Address(target_path, target_name="target")
    assert DependencyRuleApplication(
        action=DependencyRuleAction(expected_action),
        rule_description=expected_rule,
        origin_address=origin_address,
        origin_type="origin_target",
        dependency_address=dependency_address,
        dependency_type="dependency_target",
    ) == BuildFileVisibilityRules.check_dependency_rules(
        origin_address=origin_address,
        origin_adaptor=TargetAdaptor("origin_target", "source"),
        dependencies_rules=dependencies_rules,
        dependency_address=dependency_address,
        dependency_adaptor=TargetAdaptor("dependency_target", "target"),
        dependents_rules=dependents_rules,
    )


# -----------------------------------------------------------------------------------------------
# BUILD file level tests.
# -----------------------------------------------------------------------------------------------


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *visibility_rules(),
            QueryRule(DependenciesRuleApplication, (DependenciesRuleApplicationRequest,)),
        ],
        target_types=[FilesGeneratorTarget, GenericTarget, ResourcesGeneratorTarget],
    )


def denied(pattern: str = "!*", side: int = 1):
    build_files = (
        f"src/origin -> src/dependency/BUILD[{pattern}]"
        if side > 0
        else f"src/origin/BUILD[{pattern}] -> src/dependency"
    )
    return pytest.raises(
        DependencyRuleActionDeniedError,
        match=re.escape(
            dedent(
                f"""\
                src/origin:origin has 1 dependency violation:

                  * {build_files} : DENY
                    target src/origin:origin -> target src/dependency:dependency
                """
            ).strip()
        ),
    )


@pytest.mark.parametrize(
    "rules, expect_error",
    [
        (["*"], None),
        (["!*"], denied()),
        (["src/origin", "!*"], None),
        (["!src/origin", "*"], denied("!src/origin")),
        (["!src/origin/nested", "*"], None),
        (["src/origin/nested", "!*"], denied()),
        (["!src/a", "!src/b", "!src/origin", "!src/c", "*"], denied("!src/origin")),
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
        DependenciesRuleApplication,
        [
            DependenciesRuleApplicationRequest(
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
        (["src/dependency/nested", "!*"], denied(side=-1)),
        (["src/*", "!*"], None),
        (["!src/*", "*"], denied("!src/*", side=-1)),
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
        DependenciesRuleApplication,
        [
            DependenciesRuleApplicationRequest(
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
        DependenciesRuleApplication,
        [
            DependenciesRuleApplicationRequest(
                source,
                dependencies=addresses,
                description_of_origin=desc,
            )
        ],
    )

    expected = {address: action for address, (_, action) in zip(addresses, dependencies)}
    assert expected == {addr: rule.action for addr, rule in rsp.dependencies_rule.items()}


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
                  (resources, "!nope"),
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

    msg = softwrap(
        """
        There is no matching rule from the `__dependencies_rules__` defined in src/BUILD for the
        `resources` target src:res for the dependency on the `target` target src:tgt

        Consider adding the required catch-all rule at the end of the rules spec. Example adding a
        "deny all" at the end:

          (('resources',), '!nope', '!*')
        """
    )
    with engine_error(BuildFileVisibilityRulesError, contains=msg):
        rule_runner.request(
            DependenciesRuleApplication,
            [
                DependenciesRuleApplicationRequest(
                    Address("src", target_name="res"),
                    dependencies=Addresses([Address("src", target_name="tgt")]),
                    description_of_origin=repr("test"),
                )
            ],
        )

    msg = softwrap(
        """
        There is no matching rule from the `__dependents_rules__` defined in src/BUILD for the
        `target` target src:tgt for the dependency on the `resources` target src:res

        Consider adding the required catch-all rule at the end of the rules spec. Example adding a
        "deny all" at the end:

          (('resources',), 'res/*', '!*')
        """
    )
    with engine_error(BuildFileVisibilityRulesError, contains=msg):
        rule_runner.request(
            DependenciesRuleApplication,
            [
                DependenciesRuleApplicationRequest(
                    Address("src", target_name="tgt"),
                    dependencies=Addresses([Address("src", target_name="res")]),
                    description_of_origin=repr("test"),
                )
            ],
        )


def test_gitignore_style_syntax(rule_runner: RuleRunner) -> None:
    allowed = DependencyRuleAction.ALLOW
    denied = DependencyRuleAction.DENY
    warned = DependencyRuleAction.WARN

    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """
                __dependencies_rules__(
                  (
                    "*",
                    '''
                    # Anything in `pub` directories
                    pub/*

                    # Everything rooted in `src/inc`
                    /inc/**

                    # Nothing from `src/priv/` trees
                    !src/priv/**
                    ''',

                    # Warn for anything else
                    "?*",
                  ),
                )
                """
            ),
            "src/proj/BUILD": "files(name='a')",
            "src/inc/proj/interfaces/BUILD": "files()",
            "src/proj/pub/docs/BUILD": "files()",
            "src/proj/pub/docs/internal/BUILD": "files()",
            "tests/proj/src/priv/data/BUILD": "files()",
        },
    )

    assert_dependency_rules(
        rule_runner,
        "src/proj:a",
        ("src/inc/proj/interfaces", allowed),
        ("src/proj/pub/docs", allowed),
        (
            "src/proj/pub/docs/internal",
            warned,
        ),
        ("tests/proj/src/priv/data", denied),
    )
