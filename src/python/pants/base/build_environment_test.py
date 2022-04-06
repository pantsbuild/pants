# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os

import pytest

from pants.base.build_environment import MaybeGitBinary, get_pants_cachedir, rules
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner
from pants.util.contextutil import environment_as, temporary_file


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *rules(),
            QueryRule(MaybeGitBinary, []),
        ],
    )


def test_get_pants_cachedir() -> None:
    with environment_as(XDG_CACHE_HOME=""):
        assert os.path.expanduser("~/.cache/pants") == get_pants_cachedir()
    with temporary_file() as temp, environment_as(XDG_CACHE_HOME=temp.name):
        assert os.path.join(temp.name, "pants") == get_pants_cachedir()


def test_git_rule(rule_runner: RuleRunner) -> None:
    maybe_git_binary = rule_runner.request(
        MaybeGitBinary,
        [],
    )

    assert maybe_git_binary.git is None
