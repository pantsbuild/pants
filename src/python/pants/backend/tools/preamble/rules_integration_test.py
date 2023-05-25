# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import datetime

import pytest
from freezegun import freeze_time

from pants.backend.tools.preamble.rules import PreambleRequest, _substituted_template
from pants.backend.tools.preamble.rules import rules as preamble_rules
from pants.core.goals.fmt import FmtResult
from pants.engine.fs import PathGlobs
from pants.engine.internals.native_engine import Snapshot
from pants.testutil.rule_runner import QueryRule, RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *preamble_rules(),
            QueryRule(FmtResult, [PreambleRequest.Batch]),
        ],
    )


@pytest.fixture(autouse=True)
def handle_memos():
    _substituted_template.forget()


def run_preamble(rule_runner: RuleRunner, template_by_globs: dict[str, str]) -> FmtResult:
    rule_runner.set_options(
        [
            "--backend-packages=pants.backend.tools.preamble",
            f"--preamble-template-by-globs={template_by_globs!r}",
        ],
    )
    snapshot = rule_runner.request(Snapshot, [PathGlobs(["**/*.py", "**/*.rs"])])
    fmt_result = rule_runner.request(
        FmtResult,
        [
            PreambleRequest.Batch("", snapshot.files, partition_metadata=None, snapshot=snapshot),
        ],
    )
    return fmt_result


def test_passing(rule_runner: RuleRunner) -> None:
    files = {
        "foo.py": "# Copyright 1853\n...",
        "foo.rs": "// Copyright 1853\n...",
        "sub/foo.py": "# Copyright 1853\n...",
        "sub/foo.rs": "// Copyright 1853\n...",
    }
    rule_runner.write_files(files)
    fmt_result = run_preamble(
        rule_runner,
        {
            "**/*.py": "# Copyright $year\n",
            "**/*.rs": "// Copyright $year\n",
        },
    )
    assert fmt_result.output == rule_runner.make_snapshot(files)
    assert fmt_result.did_change is False


@pytest.mark.parametrize(
    "preamble, content",
    [
        ("# Copyright (c) $year", "# Copyright (c) 1853"),
        ("# Copyright (c) $$year", "# Copyright (c) $year"),
        ("# Copyright (c) ${year}", "# Copyright (c) 1853"),
        ("# Copyright (c) YEAR${year}", "# Copyright (c) YEAR1853"),
        ("# Copyright (c) $${year}", "# Copyright (c) ${year}"),
    ],
)
def test_substitution_fun(rule_runner: RuleRunner, preamble: str, content: str) -> None:
    files = {
        "foo.py": content,
    }
    rule_runner.write_files(files)
    fmt_result = run_preamble(rule_runner, {"*": preamble})
    assert fmt_result.output == rule_runner.make_snapshot(files)
    assert fmt_result.did_change is False


@freeze_time(datetime.datetime(2020, 1, 1, 12, 0, 0))
def test_failing(rule_runner: RuleRunner) -> None:
    files_before = {
        "foo.py": "...",
        "foo.rs": "...",
        "sub/foo.py": "...",
        "sub/foo.rs": "...",
    }
    files_after = {
        "foo.py": "# Copyright 2020\n...",
        "foo.rs": "// Copyright 2020\n...",
        "sub/foo.py": "# Copyright 2020\n...",
        "sub/foo.rs": "// Copyright 2020\n...",
    }

    rule_runner.write_files(files_before)
    fmt_result = run_preamble(
        rule_runner,
        {
            "*.py": "# Copyright $year\n",
            "*.rs": "// Copyright $year\n",
        },
    )
    assert fmt_result.output == rule_runner.make_snapshot(
        {
            **{key: value for key, value in files_before.items() if key.startswith("sub/")},
            **{key: value for key, value in files_after.items() if not key.startswith("sub/")},
        }
    )
    assert fmt_result.did_change
    fmt_result = run_preamble(
        rule_runner,
        {
            "**/*.py": "# Copyright $year\n",
            "**/*.rs": "// Copyright $year\n",
        },
    )
    assert fmt_result.output == rule_runner.make_snapshot(files_after)
    assert fmt_result.did_change


def test_ignores_shebang(rule_runner: RuleRunner) -> None:
    files_before = {"foo.py": "#!/usr/bin/env python3\n# Copyright"}

    rule_runner.write_files(files_before)
    fmt_result = run_preamble(
        rule_runner,
        {
            "*": "# Copyright",
        },
    )
    assert fmt_result.did_change is False


def test_preserves_shebang(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo.py": "#!/usr/bin/env python3\n...",
        }
    )
    fmt_result = run_preamble(
        rule_runner,
        {
            "**/*.py": "# Copyright\n",
        },
    )

    assert fmt_result.did_change is True
    assert fmt_result.output == rule_runner.make_snapshot(
        {
            "foo.py": "#!/usr/bin/env python3\n# Copyright\n...",
        }
    )


def test_preamble_includes_shebang(rule_runner: RuleRunner) -> None:
    files_before = {"foo.py": "#!/usr/bin/env python3\n# Copyright"}

    rule_runner.write_files(files_before)
    fmt_result = run_preamble(
        rule_runner,
        {
            "*": "#!/usr/bin/env python3\n# Copyright",
        },
    )
    assert fmt_result.did_change is False


def test_multi_glob(rule_runner: RuleRunner) -> None:
    files_before = {"foo.py": ""}

    rule_runner.write_files(files_before)
    fmt_result = run_preamble(
        rule_runner,
        {
            "*.sh:*.py": "# Copyright",
        },
    )
    assert fmt_result.did_change
    fmt_result = run_preamble(
        rule_runner,
        {
            "*.sh:*.py:!foo.py": "# Copyright",
        },
    )
    assert fmt_result.did_change is False
    fmt_result = run_preamble(
        rule_runner,
        {
            "*.sh:*.py:!foo.py": "# Copyright",
            "foo.py": "# Copywrong",
        },
    )
    assert fmt_result.did_change
