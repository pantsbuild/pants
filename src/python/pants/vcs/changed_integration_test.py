# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
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

        project = {
            ".gitignore": dedent(
                f"""\
                {Path(worktree).relative_to(get_buildroot())}
                .pants.d/pids
                __pycache__
                .coverage.*  # For some reason, CI adds these files
                """
            ),
            "app.sh": "source dep.sh",
            "dep.sh": "source transitive.sh",
            "transitive.sh": "",
            "standalone.sh": "",
            "BUILD": dedent(
                """\
                # Use a target generator to test some of its semantics.
                shell_sources(
                    name="lib",
                    sources=["app.sh", "dep.sh", "transitive.sh", "!standalone.sh"],
                    tags=["a"],
                    overrides={
                        "dep.sh": {"tags": ["b"]},
                    },
                )

                shell_source(
                    name="standalone",
                    source="standalone.sh",
                    tags=["a"],
                )
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


def append_to_file(fp: str, content: str) -> None:
    with Path(fp).open("a") as f:
        f.write(content)


def delete_file(fp: str) -> None:
    Path(fp).unlink()


def reset_edits() -> None:
    _run_git(["checkout", "--", "."])


def _run_pants_goal(
    workdir: str,
    goal: str,
    dependents: DependentsOption = DependentsOption.NONE,
    *,
    extra_args: list[str] | None = None,
) -> PantsResult:
    return run_pants_with_workdir(
        [
            *(extra_args or ()),
            "--changed-since=HEAD",
            "--print-stacktrace",
            f"--changed-dependents={dependents.value}",
            goal,
        ],
        workdir=workdir,
        config={"GLOBAL": {"backend_packages": ["pants.backend.shell"]}},
    )


def assert_list_stdout(
    workdir: str,
    expected: list[str],
    dependents: DependentsOption = DependentsOption.NONE,
    *,
    extra_args: list[str] | None = None,
) -> None:
    result = _run_pants_goal(workdir, "list", dependents=dependents, extra_args=extra_args)
    result.assert_success()
    assert sorted(result.stdout.strip().splitlines()) == sorted(expected)


def assert_count_loc(
    workdir: str,
    dependents: DependentsOption = DependentsOption.NONE,
    *,
    expected_num_files: int,
    extra_args: list[str] | None = None,
) -> None:
    result = _run_pants_goal(workdir, "count-loc", dependents=dependents, extra_args=extra_args)
    result.assert_success()
    if expected_num_files:
        assert f"Total                        {expected_num_files}" in result.stdout
    else:
        assert not result.stdout


def test_no_changes(repo: str) -> None:
    assert_list_stdout(repo, [])
    assert_count_loc(repo, expected_num_files=0)


def test_change_no_deps(repo: str) -> None:
    append_to_file("standalone.sh", "# foo")
    for dependents in DependentsOption:
        assert_list_stdout(repo, ["//:standalone"], dependents)
        assert_count_loc(repo, expected_num_files=1)


def test_change_transitive_dep(repo: str) -> None:
    append_to_file("transitive.sh", "# foo")
    assert_list_stdout(repo, ["//transitive.sh:lib"])
    assert_count_loc(repo, expected_num_files=1)

    assert_list_stdout(repo, ["//dep.sh:lib", "//transitive.sh:lib"], DependentsOption.DIRECT)
    assert_count_loc(repo, DependentsOption.DIRECT, expected_num_files=2)

    assert_list_stdout(
        repo, ["//app.sh:lib", "//dep.sh:lib", "//transitive.sh:lib"], DependentsOption.TRANSITIVE
    )

    assert_count_loc(repo, DependentsOption.TRANSITIVE, expected_num_files=3)


def test_unowned_file(repo: str) -> None:
    """Unowned files should still work with target-less goals like `count-loc`.

    If a file was removed, the target-less goals should simply ignore it.
    """
    create_file("dir/some_file.sh", "# blah")
    assert_count_loc(repo, expected_num_files=1)
    assert_list_stdout(repo, [])

    delete_file("dir/some_file.sh")
    assert_count_loc(repo, expected_num_files=0)


def test_delete_generated_target(repo: str) -> None:
    """If a generated target is deleted, we claim the target generator was modified.

    It's unlikely these are actually the semantics we want...See:
    * https://github.com/pantsbuild/pants/issues/13232
    * https://github.com/pantsbuild/pants/issues/14975
    """
    delete_file("transitive.sh")
    for dependents in DependentsOption:
        assert_list_stdout(repo, ["//:lib"], dependents)
        assert_count_loc(repo, dependents, expected_num_files=2)

    # Make sure that our fix for https://github.com/pantsbuild/pants/issues/15544 does not break
    # this test when using `--tag`.
    for dependents in (DependentsOption.NONE, DependentsOption.TRANSITIVE):
        assert_list_stdout(repo, ["//:lib"], dependents, extra_args=["--tag=a"])
        assert_count_loc(repo, dependents, expected_num_files=1, extra_args=["--tag=a"])

    # If we also edit a sibling generated target, we should still (for now at least) include the
    # target generator.
    append_to_file("app.sh", "# foo")
    for dependents in DependentsOption:
        assert_list_stdout(repo, ["//:lib", "//app.sh:lib"], dependents)
        assert_count_loc(repo, dependents, expected_num_files=2)


def test_delete_atom_target(repo: str) -> None:
    delete_file("standalone.sh")
    assert_list_stdout(repo, ["//:standalone"])

    # The target-less goal code path will trigger checking that `sources` are valid.
    result = _run_pants_goal(repo, "count-loc")
    result.assert_failure()
    assert "must have 1 file, but it had 0 files." in result.stderr


def test_change_build_file(repo: str) -> None:
    """Every target in a BUILD file is changed when it's edited.

    This is because we don't know what the target was like before-hand, so we're overly
    conservative.
    """
    append_to_file("BUILD", "# foo")
    # Note that the target generator `//:lib` does not show up.
    assert_list_stdout(
        repo, ["//app.sh:lib", "//dep.sh:lib", "//transitive.sh:lib", "//:standalone"]
    )

    # This is because the BUILD file gets expanded with all its targets, then their sources are
    # used. This might not be desirable behavior.
    assert_count_loc(repo, expected_num_files=4)


def test_different_build_file_changed(repo: str) -> None:
    """Only invalidate if the BUILD file where a target is defined has changed, even if the changed
    BUILD file is in the same directory."""
    create_file("BUILD.txt", "")
    assert_list_stdout(repo, [])
    assert_count_loc(repo, expected_num_files=1)


def test_tag_filtering(repo: str) -> None:
    append_to_file("dep.sh", "# foo")
    append_to_file("standalone.sh", "# foo")

    assert_list_stdout(repo, ["//dep.sh:lib", "//:standalone"])
    assert_count_loc(repo, expected_num_files=2)

    assert_list_stdout(repo, ["//dep.sh:lib"], extra_args=["--tag=+b"])
    assert_count_loc(repo, expected_num_files=1, extra_args=["--tag=+b"])

    assert_list_stdout(repo, ["//:standalone"], extra_args=["--tag=-b"])
    assert_count_loc(repo, expected_num_files=1, extra_args=["--tag=-b"])

    assert_list_stdout(repo, ["//dep.sh:lib"], DependentsOption.TRANSITIVE, extra_args=["--tag=+b"])
    assert_count_loc(
        repo, DependentsOption.TRANSITIVE, expected_num_files=1, extra_args=["--tag=+b"]
    )

    # Regression test for https://github.com/pantsbuild/pants/issues/14977: make sure a generated
    # target w/ different tags via `overrides` is excluded no matter what.
    reset_edits()
    append_to_file("transitive.sh", "# foo")
    assert_list_stdout(
        repo,
        ["//app.sh:lib", "//transitive.sh:lib"],
        DependentsOption.TRANSITIVE,
        extra_args=["--tag=-b"],
    )
    assert_count_loc(
        repo, DependentsOption.TRANSITIVE, expected_num_files=2, extra_args=["--tag=-b"]
    )

    # Regression test for https://github.com/pantsbuild/pants/issues/15544. Don't filter
    # `--changed-since` roots until the very end if using `--changed-dependents`.
    #
    # We change `dep.sh`, which has the tag `b`. When we filter for only tag `a`, we should still
    # find the dependents of `dep.sh`, like `app.sh`, and only then apply the filter.
    reset_edits()
    append_to_file("dep.sh", "# foo")
    assert_list_stdout(repo, [], DependentsOption.NONE, extra_args=["--tag=a"])
    assert_count_loc(repo, DependentsOption.NONE, expected_num_files=0, extra_args=["--tag=a"])

    assert_list_stdout(repo, ["//app.sh:lib"], DependentsOption.TRANSITIVE, extra_args=["--tag=a"])
    assert_count_loc(
        repo, DependentsOption.TRANSITIVE, expected_num_files=1, extra_args=["--tag=a"]
    )


def test_pants_ignored_file(repo: str) -> None:
    """Regression test for
    https://github.com/pantsbuild/pants/issues/15655#issuecomment-1140081185."""
    create_file(".ignored/f.txt", "")
    for dependents in (DependentsOption.NONE, DependentsOption.DIRECT):
        assert_list_stdout(repo, [], dependents)
        assert_count_loc(repo, dependents, expected_num_files=0)
