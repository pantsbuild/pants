# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import re
from textwrap import dedent

from pants.backend.project_info.list_targets import ListSubsystem, list_targets
from pants.engine.addresses import Address, Addresses
from pants.engine.target import DescriptionField, Target, UnexpandedTargets
from pants.testutil.option_util import create_goal_subsystem, create_options_bootstrapper
from pants.testutil.rule_runner import MockGet, mock_console, run_rule_with_mocks


class MockTarget(Target):
    alias = "tgt"
    core_fields = (DescriptionField,)


def run_goal(targets: list[MockTarget], *, show_documented: bool = False) -> tuple[str, str]:
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
                ),
                console,
            ],
            mock_gets=[
                MockGet(
                    output_type=UnexpandedTargets,
                    input_types=(Addresses,),
                    mock=lambda _: UnexpandedTargets(targets),
                )
            ],
        )
        return stdio_reader.get_stdout(), stdio_reader.get_stderr()


def test_list_normal() -> None:
    # Note that these are unsorted and that we include generated targets.
    addresses = (
        Address("", target_name="t2"),
        Address("", target_name="t1"),
        Address("", target_name="gen", relative_file_path="f.ext"),
        Address("", target_name="gen", generated_name="foo"),
    )
    stdout, _ = run_goal([MockTarget({}, addr) for addr in addresses])
    assert stdout == dedent(
        """\
        //:gen#foo
        //:t1
        //:t2
        //f.ext:gen
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
