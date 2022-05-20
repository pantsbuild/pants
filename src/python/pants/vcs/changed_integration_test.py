# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import subprocess
from pathlib import Path
from textwrap import dedent
from typing import Iterator

import pytest

from pants.base.build_environment import get_buildroot
from pants.testutil.pants_integration_test import run_pants_with_workdir
from pants.util.contextutil import environment_as, temporary_dir
from pants.vcs.changed import DependeesOption


def _run_git(command: list[str]) -> None:
    subprocess.run(
        ["git", *command], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


@pytest.fixture
def repo() -> Iterator[str]:
    with temporary_dir(root_dir=get_buildroot()) as worktree, environment_as(
        GIT_CONFIG_GLOBAL="/dev/null"
    ):
        _run_git(["init"])
        _run_git(["config", "user.email", "you@example.com"])
        _run_git(["config", "user.name", "Your Name"])

        project = {
            ".gitignore": dedent(
                f"""\
                {worktree}
                .pids
                __pycache__
                .coverage*  # For some reason, our CI adds this file.
                """
            ),
            "pants.toml": dedent(
                """\
                [GLOBAL]
                backend_packages = ['pants.backend.shell']
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


def assert_list_stdout(
    workdir: str,
    expected: list[str],
    dependees: DependeesOption = DependeesOption.NONE,
    *,
    extra_args: list[str] | None = None,
) -> None:
    result = run_pants_with_workdir(
        [
            *(extra_args or ()),
            "--changed-since=HEAD",
            f"--changed-dependees={dependees.value}",
            "list",
        ],
        workdir=workdir,
        # We must set `hermetic=False` for some reason.
        hermetic=False,
    )
    result.assert_success()
    assert sorted(result.stdout.strip().splitlines()) == sorted(expected)


def assert_count_loc(
    workdir: str, *, expected_num_files: int, extra_args: list[str] | None = None
) -> None:
    result = run_pants_with_workdir(
        [*(extra_args or ()), "--changed-since=HEAD", "count-loc"],
        workdir=workdir,
        # We must set `hermetic=False` for some reason.
        hermetic=False,
    )
    result.assert_success()
    print(result.stdout)
    print(result.stderr)
    if expected_num_files:
        assert f"Total                        {expected_num_files}" in result.stdout
    else:
        assert not result.stdout


def test_no_changes(repo: str) -> None:
    assert_list_stdout(repo, [])


def test_change_no_deps(repo: str) -> None:
    append_to_file("standalone.sh", "# foo")
    for dependees in DependeesOption:
        assert_list_stdout(repo, ["//:standalone"], dependees=dependees)


def test_change_transitive_dep(repo: str) -> None:
    append_to_file("transitive.sh", "# foo")
    assert_list_stdout(repo, ["//transitive.sh:lib"])
    assert_list_stdout(
        repo, ["//dep.sh:lib", "//transitive.sh:lib"], dependees=DependeesOption.DIRECT
    )
    assert_list_stdout(
        repo,
        ["//app.sh:lib", "//dep.sh:lib", "//transitive.sh:lib"],
        dependees=DependeesOption.TRANSITIVE,
    )


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
    for dependees in DependeesOption:
        assert_list_stdout(repo, ["//:lib"], dependees=dependees)

    # Make sure that our fix for https://github.com/pantsbuild/pants/issues/15544 does not break
    # this test when using `--tag`.
    for dependees in (DependeesOption.NONE, DependeesOption.TRANSITIVE):
        assert_list_stdout(repo, ["//:lib"], dependees=dependees, extra_args=["--tag=a"])

    # If we also edit a sibling generated target, we should still (for now at least) include the
    # target generator.
    append_to_file("app.sh", "# foo")
    for dependees in DependeesOption:
        assert_list_stdout(repo, ["//:lib", "//app.sh:lib"], dependees=dependees)


def test_delete_atom_target(repo: str) -> None:
    delete_file("standalone.sh")
    assert_list_stdout(repo, ["//:standalone"])


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


def test_different_build_file_changed(repo: str) -> None:
    """Only invalidate if the BUILD file where a target is defined has changed, even if the changed
    BUILD file is in the same directory."""
    create_file("BUILD.other", "")
    assert_list_stdout(repo, [])


def test_tag_filtering(repo: str) -> None:
    append_to_file("dep.sh", "# foo")
    append_to_file("standalone.sh", "# foo")
    assert_list_stdout(repo, ["//dep.sh:lib"], extra_args=["--tag=+b"])
    assert_list_stdout(repo, ["//:standalone"], extra_args=["--tag=-b"])
    assert_list_stdout(
        repo, ["//dep.sh:lib"], dependees=DependeesOption.TRANSITIVE, extra_args=["--tag=+b"]
    )

    # Target-less goals should still respect the tag, per
    # https://github.com/pantsbuild/pants/pull/15479.
    assert_count_loc(repo, expected_num_files=2)
    assert_count_loc(repo, expected_num_files=1, extra_args=["--tag=-b"])

    # Regression test for https://github.com/pantsbuild/pants/issues/14977: make sure a generated
    # target w/ different tags via `overrides` is excluded no matter what.
    reset_edits()
    append_to_file("transitive.sh", "# foo")
    assert_list_stdout(
        repo,
        ["//app.sh:lib", "//transitive.sh:lib"],
        dependees=DependeesOption.TRANSITIVE,
        extra_args=["--tag=-b"],
    )

    # Regression test for https://github.com/pantsbuild/pants/issues/15544. Don't filter
    # `--changed-since` roots until the very end if using `--changed-dependees`.
    #
    # We change `dep.sh`, which has the tag `b`. When we filter for only tag `a`, we should still
    # find the dependees of `dep.sh`, like `app.sh`, and only then apply the filter.
    reset_edits()
    append_to_file("dep.sh", "# foo")
    assert_list_stdout(repo, [], dependees=DependeesOption.NONE, extra_args=["--tag=a"])
    assert_list_stdout(
        repo, ["//app.sh:lib"], dependees=DependeesOption.TRANSITIVE, extra_args=["--tag=a"]
    )
