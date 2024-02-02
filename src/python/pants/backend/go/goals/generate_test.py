# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from pants.backend.go import target_type_rules
from pants.backend.go.goals import generate
from pants.backend.go.goals.generate import GoGenerateGoal, OverwriteMergeDigests, _expand_env
from pants.backend.go.target_types import GoModTarget, GoPackageTarget
from pants.backend.go.util_rules import (
    assembly,
    build_pkg,
    build_pkg_target,
    first_party_pkg,
    go_mod,
    link,
    sdk,
    tests_analysis,
    third_party_pkg,
)
from pants.core.goals.test import get_filtered_environment
from pants.core.util_rules import source_files
from pants.core.util_rules.archive import rules as archive_rules
from pants.engine.fs import DigestContents, FileContent
from pants.engine.fs import rules as fs_rules
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import PYTHON_BOOTSTRAP_ENV, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    rule_runner = RuleRunner(
        rules=[
            *generate.rules(),
            # to avoid rule graph errors?
            *assembly.rules(),
            *build_pkg.rules(),
            *build_pkg_target.rules(),
            *first_party_pkg.rules(),
            *go_mod.rules(),
            *link.rules(),
            *sdk.rules(),
            *target_type_rules.rules(),
            *tests_analysis.rules(),
            *third_party_pkg.rules(),
            *source_files.rules(),
            *fs_rules(),
            *archive_rules(),
            get_filtered_environment,
            QueryRule(DigestContents, (OverwriteMergeDigests,)),
        ],
        target_types=[GoModTarget, GoPackageTarget],
        preserve_tmpdirs=True,
    )
    rule_runner.set_options([], env_inherit=PYTHON_BOOTSTRAP_ENV)
    return rule_runner


# Adapted from Go toolchain.
# See https://github.com/golang/go/blob/cc1b20e8adf83865a1dbffa259c7a04ef0699b43/src/os/env_test.go#L14-L67
#
# Original copyright:
#   // Copyright 2010 The Go Authors. All rights reserved.
#   // Use of this source code is governed by a BSD-style
#   // license that can be found in the LICENSE file.

_EXPAND_TEST_CASES = [
    ("", ""),
    ("$*", "all the args"),
    ("$$", "PID"),
    ("${*}", "all the args"),
    ("$1", "ARGUMENT1"),
    ("${1}", "ARGUMENT1"),
    ("now is the time", "now is the time"),
    ("$HOME", "/usr/gopher"),
    ("$home_1", "/usr/foo"),
    ("${HOME}", "/usr/gopher"),
    ("${H}OME", "(Value of H)OME"),
    ("A$$$#$1$H$home_1*B", "APIDNARGSARGUMENT1(Value of H)/usr/foo*B"),
    ("start$+middle$^end$", "start$+middle$^end$"),
    ("mixed$|bag$$$", "mixed$|bagPID$"),
    ("$", "$"),
    ("$}", "$}"),
    ("${", ""),  # invalid syntax; eat up the characters
    ("${}", ""),  # invalid syntax; eat up the characters
]


@pytest.mark.parametrize("input,output", _EXPAND_TEST_CASES)
def test_expand_env(input, output) -> None:
    m = {
        "*": "all the args",
        "#": "NARGS",
        "$": "PID",
        "1": "ARGUMENT1",
        "HOME": "/usr/gopher",
        "H": "(Value of H)",
        "home_1": "/usr/foo",
        "_": "underscore",
    }
    assert _expand_env(input, m) == output


def test_generate_run_commands(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "grok/BUILD": "go_mod(name='mod')\ngo_package()",
            "grok/go.mod": "module example.com/grok\n",
            "grok/gen.go": textwrap.dedent(
                """\
            //go:build generate
            package grok
            //go:generate -command shell /bin/sh -c
            //go:generate shell "echo grok-$GOLINE > generated.txt"
            """
            ),
            "grok/empty.go": "package grok\n",
        }
    )
    result = rule_runner.run_goal_rule(GoGenerateGoal, args=["grok::"], env_inherit={"PATH"})
    assert result.exit_code == 0
    generated_file = Path(rule_runner.build_root, "grok", "generated.txt")
    assert generated_file.read_text() == "grok-4\n"


def test_overwrite_merge_digests(rule_runner: RuleRunner) -> None:
    orig_snapshot = rule_runner.make_snapshot(
        {
            "dir1/orig.txt": "orig",
            "dir1/foo/only-orig.txt": "orig",
            "dir1/shared.txt": "orig",
        }
    )
    new_snapshot = rule_runner.make_snapshot(
        {
            "dir1/new.txt": "new",
            "dir1/bar/only-new.txt": "new",
            "dir1/shared.txt": "new",
        }
    )
    raw_entries = rule_runner.request(
        DigestContents, [OverwriteMergeDigests(orig_snapshot.digest, new_snapshot.digest)]
    )
    entries = sorted(raw_entries, key=lambda elem: elem.path)
    assert entries == [
        FileContent(
            path="dir1/bar/only-new.txt",
            content=b"new",
        ),
        FileContent(
            path="dir1/foo/only-orig.txt",
            content=b"orig",
        ),
        FileContent(
            path="dir1/new.txt",
            content=b"new",
        ),
        FileContent(
            path="dir1/orig.txt",
            content=b"orig",
        ),
        FileContent(
            path="dir1/shared.txt",
            content=b"new",
        ),
    ]
