# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.java.compile.javac import rules as javac_rules
from pants.backend.java.compile.javac_binary import rules as javac_binary_rules
from pants.backend.java.dependency_inference.import_parser import (
    ParsedJavaImports,
    ParseJavaImportsRequest,
)
from pants.backend.java.dependency_inference.import_parser import rules as import_parser_rules
from pants.backend.java.dependency_inference.java_parser import rules as java_parser_rules
from pants.backend.java.dependency_inference.java_parser_launcher import (
    rules as java_parser_launcher_rules,
)
from pants.backend.java.target_types import JavaLibrary, JavaSources
from pants.core.util_rules import config_files, source_files
from pants.core.util_rules.external_tool import rules as external_tool_rules
from pants.engine.addresses import UnparsedAddressInputs
from pants.engine.process import rules as process_rules
from pants.engine.target import Targets
from pants.jvm.resolve.coursier_fetch import rules as coursier_fetch_rules
from pants.jvm.resolve.coursier_setup import rules as coursier_setup_rules
from pants.jvm.util_rules import rules as util_rules
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *config_files.rules(),
            *coursier_fetch_rules(),
            *coursier_setup_rules(),
            *external_tool_rules(),
            *import_parser_rules(),
            *java_parser_launcher_rules(),
            *java_parser_rules(),
            *javac_binary_rules(),
            *javac_rules(),
            *process_rules(),
            *source_files.rules(),
            *util_rules(),
            QueryRule(ParsedJavaImports, [ParseJavaImportsRequest]),
            QueryRule(Targets, [UnparsedAddressInputs]),
        ],
        target_types=[JavaLibrary],
        bootstrap_args=["--javac-jdk=system"],  # TODO(#12293): use a fixed JDK version.
    )


# def test_regex_parse():
#     assert (
#         regex_parse_java_imports(
#             dedent(
#                 """\
#                 package org.pantsbuild.example;

#                 import org.pantsbuild.example.lib.ExampleLib;

#                 public class Example {}
#                 """
#             )
#         )
#         == frozenset(["org.pantsbuild.example.lib"])
#     )

#     assert (
#         regex_parse_java_imports(
#             dedent(
#                 """\
#                 import org.pantsbuild.example.lib.ExampleLib;

#                 public class Example {}
#                 """
#             )
#         )
#         == frozenset(["org.pantsbuild.example.lib"])
#     )

#     assert (
#         regex_parse_java_imports(
#             dedent(
#                 """\
#                 import org.pantsbuild.example.lib.*;

#                 public class Example {}
#                 """
#             )
#         )
#         == frozenset(["org.pantsbuild.example.lib"])
#     )

#     assert (
#         regex_parse_java_imports(
#             dedent(
#                 """\
#                 import GlobalType;

#                 public class Example {}
#                 """
#             )
#         )
#         == frozenset()
#     )

#     assert (
#         regex_parse_java_imports(
#             dedent(
#                 """\
#                 import foo.*;

#                 public class Example {}
#                 """
#             )
#         )
#         == frozenset(["foo"])
#     )


# def test_regex_parse_no_static():
#     assert (
#         regex_parse_java_imports(
#             dedent(
#                 """\
#                 import static foo.*;

#                 public class Example {}
#                 """
#             )
#         )
#         == frozenset()
#     )


def test_parse_java_imports(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_library(name = 'lib')
                """
            ),
            "ExampleLib.java": dedent(
                """\
                import org.pantsbuild.example.foo.Foo;

                public class ExampleLib {}
                """
            ),
        }
    )

    target = rule_runner.request(
        Targets, [UnparsedAddressInputs(["//:lib"], owning_address=None)]
    ).expect_single()
    assert (
        rule_runner.request(
            ParsedJavaImports,
            [
                ParseJavaImportsRequest(
                    sources=target[JavaSources],
                )
            ],
        )
        == ParsedJavaImports(["org.pantsbuild.example.foo.Foo"])
    )


def test_parse_java_imports_subtargets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                java_library(name = 'lib')
                """
            ),
            "ExampleLib.java": dedent(
                """\
                import org.pantsbuild.example.foo.Foo;

                public class ExampleLib {}
                """
            ),
            "OtherLib.java": dedent(
                """\
                import org.pantsbuild.example.bar.Bar;

                public class OtherLib {}
                """
            ),
        }
    )

    targets = rule_runner.request(Targets, [UnparsedAddressInputs(["//:lib"], owning_address=None)])
    assert [target.address.spec for target in targets] == [
        "//ExampleLib.java:lib",
        "//OtherLib.java:lib",
    ]
    assert (
        rule_runner.request(
            ParsedJavaImports,
            [
                ParseJavaImportsRequest(
                    sources=targets[0][JavaSources],
                )
            ],
        )
        == ParsedJavaImports(["org.pantsbuild.example.foo.Foo"])
    )
    assert (
        rule_runner.request(
            ParsedJavaImports,
            [
                ParseJavaImportsRequest(
                    sources=targets[1][JavaSources],
                )
            ],
        )
        == ParsedJavaImports(["org.pantsbuild.example.bar.Bar"])
    )
