# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.core.target_types import Files, GenRuleTarget
from pants.core.target_types import rules as target_type_rules
from pants.core.util_rules.gen_rule import GenerateFilesFromGenRuleRequest
from pants.core.util_rules.gen_rule import rules as gen_rules
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address
from pants.engine.fs import EMPTY_SNAPSHOT, DigestContents
from pants.engine.target import GeneratedSources, TransitiveTargets, TransitiveTargetsRequest
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *gen_rules(),
            *source_files_rules(),
            *target_type_rules(),
            QueryRule(GeneratedSources, [GenerateFilesFromGenRuleRequest]),
            QueryRule(TransitiveTargets, [TransitiveTargetsRequest]),
            QueryRule(SourceFiles, [SourceFilesRequest]),
        ],
        target_types=[GenRuleTarget, Files],
    )


def assert_gen_rule_result(
    rule_runner: RuleRunner, address: Address, expected_contents: dict[str, str]
) -> None:
    target = rule_runner.get_target(address)
    result = rule_runner.request(
        GeneratedSources, [GenerateFilesFromGenRuleRequest(EMPTY_SNAPSHOT, target)]
    )
    assert result.snapshot.files == tuple(expected_contents)
    contents = rule_runner.request(DigestContents, [result.snapshot.digest])
    for fc in contents:
        assert fc.content == expected_contents[fc.path].encode()


def test_sources_and_files(rule_runner: RuleRunner) -> None:
    MSG = ["Hello gen_rule", ", nice cut."]
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                gen_rule(
                  name="hello",
                  sources=["script"],
                  dependencies=[":files"],
                  tools=[
                    "cat",
                    "mkdir",
                    "tee",
                  ],
                  outputs=["message.txt", "res/"],
                  command="source ./script",
                )

                files(
                  name="files",
                  sources=["*.txt"],
                )
                """
            ),
            "src/intro.txt": MSG[0],
            "src/outro.txt": MSG[1],
            "src/script": (
                "$mkdir res && $cat *.txt > message.txt && $cat message.txt | $tee res/log.txt"
            ),
        }
    )

    RES = "".join(MSG)
    assert_gen_rule_result(
        rule_runner,
        Address("src", target_name="hello"),
        expected_contents={
            "src/message.txt": RES,
            "src/res/log.txt": RES,
        },
    )


def test_quotes_command(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/BUILD": dedent(
                """\
                gen_rule(
                  name="quotes",
                  tools=["echo", "tee"],
                  command='$echo "foo bar" | $tee out.log',
                  outputs=["out.log"],
                )
                """
            ),
        }
    )

    assert_gen_rule_result(
        rule_runner,
        Address("src", target_name="quotes"),
        expected_contents={"src/out.log": "foo bar\n"},
    )


def test_chained_gen_rules(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/a/BUILD": dedent(
                """\
                gen_rule(
                  name="msg",
                  tools=["echo"],
                  outputs=["msg"],
                  command="$echo 'gen_rule:a' > msg",
                )
                """
            ),
            "src/b/BUILD": dedent(
                """\
                gen_rule(
                  name="msg",
                  tools=["cp", "echo"],
                  outputs=["msg"],
                  command="$cp ../a/msg . ; $echo 'gen_rule:b' >> msg",
                  dependencies=["src/a:msg"],
                )
                """
            ),
        }
    )

    assert_gen_rule_result(
        rule_runner,
        Address("src/a", target_name="msg"),
        expected_contents={"src/a/msg": "gen_rule:a\n"},
    )

    assert_gen_rule_result(
        rule_runner,
        Address("src/b", target_name="msg"),
        expected_contents={"src/b/msg": "gen_rule:a\ngen_rule:b\n"},
    )
