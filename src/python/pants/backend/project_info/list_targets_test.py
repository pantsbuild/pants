# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from textwrap import dedent

from pants.backend.project_info.list_targets import ListSubsystem, list_targets
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.engine.addresses import Address, Addresses
from pants.engine.target import DescriptionField, ProvidesField, Target, UnexpandedTargets
from pants.testutil.option_util import create_goal_subsystem, create_options_bootstrapper
from pants.testutil.rule_runner import MockGet, mock_console, run_rule_with_mocks


class MockTarget(Target):
    alias = "tgt"
    core_fields = (DescriptionField, ProvidesField)


def run_goal(
    targets: list[MockTarget],
    *,
    show_documented: bool = False,
    show_provides: bool = False,
    provides_columns: str | None = None,
) -> tuple[str, str]:
    with mock_console(create_options_bootstrapper()) as (console, stdio_reader):
        run_rule_with_mocks(
            list_targets,
            rule_args=[
                Addresses(tgt.address for tgt in targets),
                create_goal_subsystem(
                    ListSubsystem,
                    sep="\\n",
                    output_file=None,
                    documented=show_documented,
                    provides=show_provides,
                ),
                console,
            ],
            mock_gets=[
                MockGet(
                    output_type=UnexpandedTargets,
                    input_type=Addresses,
                    mock=lambda _: UnexpandedTargets(targets),
                )
            ],
        )
        return stdio_reader.get_stdout(), stdio_reader.get_stderr()


def test_list_normal() -> None:
    # Note that these are unsorted.
    target_names = ("t3", "t2", "t1")
    stdout, _ = run_goal([MockTarget({}, Address("", target_name=name)) for name in target_names])
    assert stdout == dedent(
        """\
        //:t1
        //:t2
        //:t3
        """
    )


def test_no_targets_warns() -> None:
    _, stderr = run_goal([])
    assert "WARNING: No targets" in stderr


def test_list_documented() -> None:
    stdout, _ = run_goal(
        [
            MockTarget(
                {DescriptionField.alias: "Description of a target.\n\tThis target is the best."},
                Address("", target_name="described"),
            ),
            MockTarget({}, Address("", target_name="not_described")),
        ],
        show_documented=True,
    )
    assert stdout == dedent(
        """\
        //:described
          Description of a target.
          \tThis target is the best.
        """
    )


def test_list_provides() -> None:
    sample_artifact = PythonArtifact(name="project.demo")
    targets = [
        MockTarget({ProvidesField.alias: sample_artifact}, Address("", target_name="provided")),
        MockTarget({}, Address("", target_name="not_provided")),
    ]
    stdout, _ = run_goal(targets, show_provides=True)
    assert stdout.strip() == f"//:provided {sample_artifact}"
