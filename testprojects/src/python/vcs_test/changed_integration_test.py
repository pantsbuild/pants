# Copyright 2024 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import subprocess
from pathlib import Path
from textwrap import dedent
from typing import Iterator

import pytest

from pants.base.build_environment import get_buildroot
from pants.testutil.pants_integration_test import PantsResult, run_pants_with_workdir
from pants.util.contextutil import temporary_dir
from pants.vcs.changed import DependentsOption


def _run_git(command: list[str]) -> None:
    subprocess.run(
        ["git", *command], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


@pytest.fixture
def repo() -> Iterator[str]:
    with temporary_dir(root_dir=get_buildroot()) as worktree:
        _run_git(["init"])
        _run_git(["config", "user.email", "you@example.com"])
        _run_git(["config", "user.name", "Your Name"])
        _run_git(["config", "commit.gpgsign", "false"])

        project = {
            ".gitignore": dedent(
                f"""\
                {Path(worktree).relative_to(get_buildroot())}
                .pants.d/pids
                __pycache__
                .coverage.*  # For some reason, CI adds these files
                """
            ),
            "tables.py": dedent(
                """\
                companies = {
                    "table": "companies",
                    "colums": [
                        "id",
                        "name",
                    ],
                }

                persons = {
                    "table": "persons",
                    "colums": [
                        "id",
                        "name",
                    ],
                }

                employees = {
                    "table": "employees",
                    "colums": [
                        "company_id",
                        "person_id",
                    ],
                }
                """
            ),
            "BUILD": dedent(
                """\
                python_constants(name="tables", source="tables.py")
                """
            ),
        }
        for fp, content in project.items():
            create_file(fp, content)

        _run_git(["add", "."])
        _run_git(["commit", "-m", "blah"])
        yield worktree


def create_file(fp: str, content: str) -> None:
    full_fp = Path(fp)
    full_fp.parent.mkdir(parents=True, exist_ok=True)
    full_fp.write_text(content)


def _run_pants_goal(
    workdir: str,
    goal: str,
    dependents: DependentsOption = DependentsOption.NONE,
    *,
    changed_since: str | None = None,
    extra_args: list[str] | None = None,
) -> PantsResult:
    changed_since = changed_since or "HEAD"
    return run_pants_with_workdir(
        [
            *(extra_args or ()),
            f"--changed-since={changed_since}",
            "--print-stacktrace",
            f"--changed-dependents={dependents.value}",
            goal,
        ],
        workdir=workdir,
        config={
            "GLOBAL": {
                "backend_packages": [
                    "pants.backend.shell",
                    "pants.backend.python",
                    "python_constant",
                ]
            }
        },
    )


def assert_list_stdout(
    workdir: str,
    expected: list[str],
    dependents: DependentsOption = DependentsOption.NONE,
    *,
    changed_since: str | None = None,
    extra_args: list[str] | None = None,
) -> None:
    result = _run_pants_goal(
        workdir,
        "list",
        dependents=dependents,
        changed_since=changed_since,
        extra_args=extra_args,
    )
    result.assert_success()
    assert sorted(result.stdout.strip().splitlines()) == sorted(expected)


def test_lines_one_line_added_in_target(repo: str) -> None:
    Path("tables.py").write_text(
        dedent(
            """\
            companies = {
                "table": "companies",
                "colums": [
                    "id",
                    "name",
                ],
            }

            persons = {
                "table": "persons",
                "colums": [
                    "id",
                    "name",
                    "surname",
                ],
            }

            employees = {
                "table": "employees",
                "colums": [
                    "company_id",
                    "person_id",
                ],
            }
            """
        )
    )
    _run_git(["add", "tables.py"])
    _run_git(["commit", "-m", "Change tables.persons"])
    assert_list_stdout(
        repo,
        [
            "//:tables#persons",
        ],
        changed_since="HEAD~1",
        extra_args=["--enable-target-origin-sources-blocks"],
    )


def test_lines_one_target_deleted(repo: str) -> None:
    Path("tables.py").write_text(
        dedent(
            """\
            companies = {
                "table": "companies",
                "colums": [
                    "id",
                    "name",
                ],
            }


            employees = {
                "table": "employees",
                "colums": [
                    "company_id",
                    "person_id",
                ],
            }
            """
        )
    )
    _run_git(["add", "tables.py"])
    _run_git(["commit", "-m", "Delete tables.persons"])
    assert_list_stdout(
        repo,
        # No targets need to be triggered.
        [],
        changed_since="HEAD~1",
        extra_args=["--enable-target-origin-sources-blocks"],
    )


def test_lines_one_line_on_the_edge_deleted(repo: str) -> None:
    Path("tables.py").write_text(
        dedent(
            """\
            companies = {
                "table": "companies",
                "colums": [
                    "id",
                    "name",
                ],
            }

            persons = {
                "table": "persons",
                "colums": [
                    "id",
                    "name",
                ],
            }
            employees = {
                "table": "employees",
                "colums": [
                    "company_id",
                    "person_id",
                ],
            }
            """
        )
    )
    _run_git(["add", "tables.py"])
    _run_git(["commit", "-m", "Delete tables.persons"])
    assert_list_stdout(
        repo,
        # Adjacent targets has to be triggered, because we don't khow if the change has affected them.
        [
            "//:tables#persons",
            "//:tables#employees",
        ],
        changed_since="HEAD~1",
        extra_args=["--enable-target-origin-sources-blocks"],
    )
