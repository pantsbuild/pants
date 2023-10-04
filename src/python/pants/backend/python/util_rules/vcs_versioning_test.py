# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from pants.backend.python.subsystems import setuptools_scm
from pants.backend.python.target_types import VCSVersion
from pants.backend.python.target_types_rules import rules as python_target_types_rules
from pants.backend.python.util_rules import vcs_versioning
from pants.backend.python.util_rules.vcs_versioning import GeneratePythonFromSetuptoolsSCMRequest
from pants.build_graph.address import Address
from pants.engine.fs import DigestContents
from pants.engine.internals.native_engine import EMPTY_SNAPSHOT
from pants.engine.rules import QueryRule
from pants.engine.target import GeneratedSources
from pants.testutil.python_rule_runner import PythonRuleRunner
from pants.util.contextutil import environment_as
from pants.util.dirutil import safe_open
from pants.vcs import git


@pytest.fixture
def rule_runner() -> PythonRuleRunner:
    rule_runner = PythonRuleRunner(
        rules=[
            *vcs_versioning.rules(),
            *setuptools_scm.rules(),
            *python_target_types_rules(),
            *git.rules(),
            QueryRule(GeneratedSources, [GeneratePythonFromSetuptoolsSCMRequest]),
        ],
        target_types=[VCSVersion],
    )
    rule_runner.set_options(
        ["--backend-packages=pants.backend.python"],
        env_inherit={"PATH", "PYENV_ROOT", "HOME"},
    )
    return rule_runner


@pytest.mark.parametrize(
    "tag_regex,tag,expected_version",
    (
        # Test the default regex, to make sure we don't mess up any escaping when writing it to
        # the synthetic config file. Some of these are taken from setuptools_scm's own tests.
        (None, "11.22.33", "11.22.33"),
        (None, "v11.22.33", "11.22.33"),
        (None, "V11.22.33", "11.22.33"),
        (None, "release-v11.22.33", "11.22.33"),
        (None, "1", "1"),
        (None, "1.2", "1.2"),
        (None, "1.2.3", "1.2.3"),
        (None, "v1.0.0", "1.0.0"),
        (None, "v1.0.0-rc.1", "1.0.0rc1"),
        (None, "v1.0.0-rc.1+-25259o4382757gjurh54", "1.0.0rc1"),
        # Test a custom regex.
        (r"^version_(?P<version>.*)$", "version_11.22.33", "11.22.33"),
    ),
)
def test_vcs_versioning(
    tag_regex, tag, expected_version, tmp_path: Path, rule_runner: PythonRuleRunner
) -> None:
    worktree = tmp_path / "worktree"
    gitdir = worktree / ".git"
    with safe_open(worktree / "README", "w") as f:
        f.write("dummy content")
    tag_regex_field = "" if tag_regex is None else f"tag_regex='{tag_regex}',"
    rule_runner.write_files(
        {
            "src/python/BUILD": textwrap.dedent(
                f"""
        vcs_version(
            name="version",
            {tag_regex_field}
            generate_to="src/python/_version.py",
            template ='version = "{{version}}"'
        )
        """
            )
        }
    )
    address = Address("src/python", target_name="version")
    tgt = rule_runner.get_target(address)

    with environment_as(
        GIT_DIR=str(gitdir),
        GIT_WORK_TREE=str(worktree),
        GIT_CONFIG_GLOBAL="/dev/null",
    ):
        subprocess.check_call(["git", "init"])
        subprocess.check_call(["git", "config", "user.email", "you@example.com"])
        subprocess.check_call(["git", "config", "user.name", "Your Name"])
        subprocess.check_call(["git", "add", "."])
        subprocess.check_call(["git", "commit", "-am", "Add project files."])
        subprocess.check_call(["git", "tag", tag])

        generated_sources = rule_runner.request(
            GeneratedSources, [GeneratePythonFromSetuptoolsSCMRequest(EMPTY_SNAPSHOT, tgt)]
        )
        assert generated_sources.snapshot.files == ("src/python/_version.py",)
        dc = rule_runner.request(DigestContents, [generated_sources.snapshot.digest])
        assert len(dc) == 1
        fc = dc[0]
        assert fc.path == "src/python/_version.py"
        assert fc.content.decode() == f'version = "{expected_version}"'
        assert fc.is_executable is False
