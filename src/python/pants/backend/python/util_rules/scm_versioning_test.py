# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from pants.backend.python.subsystems import setuptools_scm
from pants.backend.python.target_types import SetuptoolsSCMVersion
from pants.backend.python.target_types_rules import rules as python_target_types_rules
from pants.backend.python.util_rules import scm_versioning
from pants.backend.python.util_rules.scm_versioning import GeneratePythonFromSetuptoolsSCMRequest
from pants.build_graph.address import Address
from pants.engine.fs import DigestContents
from pants.engine.internals.native_engine import EMPTY_SNAPSHOT
from pants.engine.rules import QueryRule
from pants.engine.target import GeneratedSources
from pants.testutil.rule_runner import RuleRunner
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_open
from pants.vcs import git


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *scm_versioning.rules(),
            *setuptools_scm.rules(),
            *python_target_types_rules(),
            *git.rules(),
            QueryRule(GeneratedSources, [GeneratePythonFromSetuptoolsSCMRequest]),
        ],
        target_types=[SetuptoolsSCMVersion],
    )
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return rule_runner


def test_scm_versioning(tmp_path: Path, rule_runner: RuleRunner) -> None:
    worktree = tmp_path / "worktree"
    gitdir = worktree / ".git"
    with safe_open(worktree / "README", "w") as f:
        f.write("dummy content")
    rule_runner.write_files(
        {
            "src/python/BUILD": textwrap.dedent(
                """
        setuptools_scm_version(
            name="scm_version",
            tag_regex="^version_(?P<version>.*)$",
            write_to="src/python/_version.py",
            write_to_template ='version = "{version}"'
        )
        """
            )
        }
    )
    address = Address("src/python", target_name="scm_version")
    tgt = rule_runner.get_target(address)

    with environment_as(
        GIT_DIR=str(gitdir),
        GIT_WORK_TREE=str(worktree),
        GIT_CONFIG_GLOBAL="/dev/null",
    ):
        subprocess.check_call(["git", "init", "--initial-branch=main"])
        subprocess.check_call(["git", "config", "user.email", "you@example.com"])
        subprocess.check_call(["git", "config", "user.name", "Your Name"])
        subprocess.check_call(["git", "add", "."])
        subprocess.check_call(["git", "commit", "-am", "Add project files."])
        subprocess.check_call(["git", "tag", "version_11.22.33"])

        generated_sources = rule_runner.request(
            GeneratedSources, [GeneratePythonFromSetuptoolsSCMRequest(EMPTY_SNAPSHOT, tgt)]
        )
        assert generated_sources.snapshot.files == ("src/python/_version.py",)
        dc = rule_runner.request(DigestContents, [generated_sources.snapshot.digest])
        assert len(dc) == 1
        fc = dc[0]
        assert fc.path == "src/python/_version.py"
        assert fc.content.decode() == 'version = "11.22.33"'
        assert fc.is_executable is False
