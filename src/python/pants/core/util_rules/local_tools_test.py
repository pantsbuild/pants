# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

import pytest

from pants.core.util_rules.local_tools import LocalTools, LocalToolsRequest, rules
from pants.engine.fs import Digest, DigestContents
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *rules(),
            QueryRule(LocalTools, [LocalToolsRequest]),
            QueryRule(DigestContents, [Digest]),
        ],
    )


def test_isolate_tool(rule_runner: RuleRunner) -> None:
    result = rule_runner.request(
        LocalTools,
        [
            LocalToolsRequest.for_tools(
                "printf",
                rationale="test the local tools feature",
                output_directory=".bin",
                search_path=("/usr/bin", "/bin", "/usr/local/bin"),
            )
        ],
    )

    assert result.bin_directory == ".bin"

    contents = rule_runner.request(DigestContents, [result.tools])
    assert len(contents) == 1

    printf_shim = contents[0]
    assert printf_shim.path == ".bin/printf"
    assert printf_shim.is_executable
    assert printf_shim.content.decode() == dedent(
        """\
        #!/bin/bash
        exec "/usr/bin/printf" "$@"
        """
    )
