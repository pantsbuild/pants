# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from textwrap import dedent

from pants.backend.project_info.list_targets import ListSubsystem, list_targets
from pants.backend.python.macros.python_artifact import PythonArtifact
from pants.engine.addresses import Address
from pants.engine.target import DescriptionField, ProvidesField, Target, Targets
from pants.testutil.option_util import create_goal_subsystem, create_options_bootstrapper
from pants.testutil.rule_runner import mock_console, run_rule_with_mocks


class MockTarget(Target):
    alias = "tgt"
    core_fields = (DescriptionField, ProvidesField)


def run_goal(
    targets: list[MockTarget], *, show_documented: bool = False, show_provides: bool = False
) -> tuple[str, str]:
    with mock_console(create_options_bootstrapper()) as (console, stdio_reader):
        run_rule_with_mocks(
            list_targets,
            rule_args=[
                Targets(targets),
                create_goal_subsystem(
                    ListSubsystem,
                    sep="\\n",
                    output_file=None,
                    documented=show_documented,
                    provides=show_provides,
                ),
                console,
            ],
        )
        return stdio_reader.get_stdout(), stdio_reader.get_stderr()


def test_list_normal() -> None:
    # Note that these are unsorted.
    target_names = ("t3", "t2", "t1")
    stdout, _ = run_goal(
        [
            *(MockTarget({}, Address("", target_name=name)) for name in target_names),
            *(
                MockTarget({}, Address("", target_name="generator", generated_name=name))
                for name in target_names
            ),
            *(
                MockTarget({}, Address("", target_name="lib", relative_file_path=f"{name}.ext"))
                for name in target_names
            ),
        ]
    )
    assert stdout == dedent(
        """\
        //:generator#t1
        //:generator#t2
        //:generator#t3
        //:t1
        //:t2
        //:t3
        //t1.ext:lib
        //t2.ext:lib
        //t3.ext:lib
        """
    )


def test_no_targets_warns() -> None:
    _, stderr = run_goal([])
    assert re.search("WARN.* No targets", stderr)


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
