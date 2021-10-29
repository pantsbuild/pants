# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.backend.docker.target_types import DockerfileTarget, DockerImageSourceField
from pants.backend.docker.util_rules.dockerfile import rules as dockerfile_rules
from pants.core.util_rules.source_files import SourceFiles, SourceFilesRequest
from pants.core.util_rules.source_files import rules as source_files_rules
from pants.engine.addresses import Address
from pants.engine.fs import DigestContents, FileContent
from pants.engine.target import SourcesField
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *dockerfile_rules(),
            *source_files_rules(),
            QueryRule(SourceFiles, [SourceFilesRequest]),
        ],
        target_types=[DockerfileTarget],
    )


def test_generate_dockerfile(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "test/BUILD": dedent(
                """\
                dockerfile(
                  name="Dockerfile.test",
                  instructions=[
                    "FROM python:3.9",
                    "ENTRYPOINT python3"
                  ]
                )
                """
            ),
        }
    )

    tgt = rule_runner.get_target(Address("test", target_name="Dockerfile.test"))
    result = rule_runner.request(
        SourceFiles,
        [
            SourceFilesRequest(
                sources_fields=[tgt.get(SourcesField)],
                for_sources_types=(DockerImageSourceField,),
                enable_codegen=True,
            )
        ],
    )

    assert result.snapshot.files == ("test/Dockerfile.test",)

    contents = rule_runner.request(DigestContents, [result.snapshot.digest])
    assert len(contents) == 1
    assert isinstance(contents[0], FileContent)
    assert contents[0].content.decode() == dedent(
        """\
        FROM python:3.9
        ENTRYPOINT python3
        """
    )
