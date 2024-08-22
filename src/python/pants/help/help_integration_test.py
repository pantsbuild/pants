# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import re
import textwrap

from pants.testutil.pants_integration_test import run_pants
from pants.util.docutil import doc_url


def test_help() -> None:
    pants_run = run_pants(["help"])
    pants_run.assert_success()
    assert "Usage:" in pants_run.stdout


def test_help_global() -> None:
    pants_run = run_pants(["help", "global"])
    pants_run.assert_success()
    assert "--level" in pants_run.stdout
    assert "Global options" in pants_run.stdout


def test_help_advanced_global() -> None:
    pants_run = run_pants(["help-advanced", "global"])
    pants_run.assert_success()
    assert "Global advanced options" in pants_run.stdout
    # Spot check to see that a global advanced option is printed
    assert "--loop-max" in pants_run.stdout


def test_help_targets() -> None:
    pants_run = run_pants(["help", "targets"])
    pants_run.assert_success()

    # The target help text may be split over several lines depending on what targets there are
    # and how Pants views the terminal size. Extract the full texts consistently to reduce this test's
    # brittle nature.
    target_help_texts: list[str] = []
    current = ""
    for line in pants_run.stdout.splitlines():
        line = line.rstrip()
        if not line:
            continue

        if not line[0:1].isspace():
            target_help_texts.append(current)
            current = ""

        line = re.sub(r"\s+", " ", line.strip())
        current += f" {line}"
    if current:
        target_help_texts.append(current)

    assert (
        " archive A ZIP or TAR file containing loose files and code packages." in target_help_texts
    )
    assert "to get help for a specific target" in pants_run.stdout


def test_help_subsystems() -> None:
    pants_run = run_pants(["--backend-packages=pants.backend.python", "help", "subsystems"])
    pants_run.assert_success()
    assert (
        "pex                     How Pants uses Pex to run Python subprocesses" in pants_run.stdout
    )
    assert "to get help for a specific subsystem" in pants_run.stdout
    assert not re.search(r"^test\s+", pants_run.stdout)


def test_help_specific_target() -> None:
    pants_run = run_pants(["help", "archive"])
    pants_run.assert_success()

    assert (
        textwrap.dedent(
            """
            `archive` target
            ----------------

            A ZIP or TAR file containing loose files and code packages.


            Activated by pants.core
            Valid fields:
            """
        )
        in pants_run.stdout
    )

    assert (
        textwrap.dedent(
            """
            format
                type: 'tar' | 'tar.bz2' | 'tar.gz' | 'tar.xz' | 'zip'
                required

                The type of archive file to be generated.
            """
        )
        in pants_run.stdout
    )


def test_help_goals() -> None:
    pants_run = run_pants(["help", "goals"])
    pants_run.assert_success()
    assert "to get help for a specific goal" in pants_run.stdout
    # Spot check a few core goals.
    for goal in ["filedeps", "list", "roots"]:
        assert goal in pants_run.stdout


def test_help_goals_only_show_implemented() -> None:
    # Some core goals, such as `./pants test`, require downstream implementations to work
    # properly. We should only show those goals when an implementation is provided.
    goals_that_need_implementation = ["fmt", "test"]
    command = ["--pants-config-files=[]", "help", "goals"]

    not_implemented_run = run_pants(["--backend-packages=[]", *command])
    not_implemented_run.assert_success()
    for goal in goals_that_need_implementation:
        assert goal not in not_implemented_run.stdout

    implemented_run = run_pants(
        [
            "--backend-packages=['pants.backend.python', 'pants.backend.python.lint.isort']",
            *command,
        ],
    )
    implemented_run.assert_success()
    for goal in goals_that_need_implementation:
        assert goal in implemented_run.stdout


def test_help_all() -> None:
    pants_run = run_pants(["--backend-packages=pants.backend.python", "help-all"])
    pants_run.assert_success()
    all_help = json.loads(pants_run.stdout)

    # Spot check the data.
    assert "name_to_goal_info" in all_help
    assert "test" in all_help["name_to_goal_info"]

    assert "scope_to_help_info" in all_help
    assert "" in all_help["scope_to_help_info"]
    assert "pytest" in all_help["scope_to_help_info"]
    assert len(all_help["scope_to_help_info"]["pytest"]["basic"]) > 0


def test_unknown_goal() -> None:
    pants_run = run_pants(["testx"])
    pants_run.assert_failure()
    assert "Unknown goal: testx" in pants_run.stdout
    assert "Did you mean test" in pants_run.stdout


def test_unknown_global_flags() -> None:
    pants_run = run_pants(["--pants-workdirx", "goals"])
    pants_run.assert_failure()
    assert "Unknown flag --pants-workdirx on global scope" in pants_run.stdout
    assert "Did you mean --pants-workdir" in pants_run.stdout


def test_unknown_scoped_flags() -> None:
    pants_run = run_pants(["test", "--forcex"])
    pants_run.assert_failure()
    assert "Unknown flag --forcex on test scope" in pants_run.stdout
    assert "Did you mean --force" in pants_run.stdout


def test_global_flag_in_scoped_position() -> None:
    pants_run = run_pants(
        ["test", "--pants-distdir=dist/"],
    )
    pants_run.assert_failure()
    assert "Unknown flag --pants-distdir on test scope" in pants_run.stdout
    assert "Did you mean to use the global --pants-distdir?" in pants_run.stdout


def test_help_provided_target_plugin_field() -> None:
    pants_run = run_pants(
        [
            "--backend-packages=['pants.backend.python', 'pants.backend.experimental.python']",
            "help",
            "python_distribution",
        ]
    )
    pants_run.assert_success()

    assert (
        textwrap.dedent(
            f"""
            `python_distribution` target
            ----------------------------

            A publishable Python setuptools distribution (e.g. an sdist or wheel).

            See {doc_url("docs/python/overview/building-distributions")}.


            Activated by pants.backend.python
            Valid fields:
            """
        )
        in pants_run.stdout
    )

    assert (
        textwrap.dedent(
            """
            skip_twine
                from: pants.backend.experimental.python
                type: bool
                default: False

                If true, don't publish this target's packages using Twine.

            tags
                type: Iterable[str] | None
                default: None

                Arbitrary strings to describe a target.
            """
        )
        in pants_run.stdout
    )


def test_help_ignore_specs() -> None:
    pants_run = run_pants(
        ["test", "src/python/pants/bsp/protocol_test.py", "--help"],
    )
    pants_run.assert_success()
    assert "`test` goal options" in pants_run.stdout
