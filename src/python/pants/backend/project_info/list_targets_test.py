# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent
from typing import List, Optional, Tuple, cast

from pants.backend.project_info.list_targets import ListSubsystem, list_targets
from pants.backend.python.python_artifact import PythonArtifact
from pants.engine.addresses import Address, Addresses
from pants.engine.target import DescriptionField, ProvidesField, Target, Targets
from pants.testutil.engine.util import MockConsole, MockGet, create_goal_subsystem, run_rule


class MockTarget(Target):
    alias = "tgt"
    core_fields = (DescriptionField, ProvidesField)


def run_goal(
    targets: List[MockTarget],
    *,
    show_documented: bool = False,
    show_provides: bool = False,
    provides_columns: Optional[str] = None,
) -> Tuple[str, str]:
    console = MockConsole(use_colors=False)
    run_rule(
        list_targets,
        rule_args=[
            Addresses(tgt.address for tgt in targets),
            create_goal_subsystem(
                ListSubsystem,
                sep="\\n",
                output_file=None,
                documented=show_documented,
                provides=show_provides,
                provides_columns=provides_columns or "address,artifact_id",
            ),
            console,
        ],
        mock_gets=[MockGet(product_type=Targets, subject_type=Addresses, mock=lambda _: targets)],
    )
    return cast(str, console.stdout.getvalue()), cast(str, console.stderr.getvalue())


def test_list_normal() -> None:
    # Note that these are unsorted.
    addresses = (":t3", ":t2", ":t1")
    stdout, _ = run_goal([MockTarget({}, address=Address.parse(addr)) for addr in addresses])
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
                address=Address.parse(":described"),
            ),
            MockTarget({}, address=Address.parse(":not_described")),
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
    sample_artifact = PythonArtifact(name="project.demo", version="0.0.0.1")
    targets = [
        MockTarget({ProvidesField.alias: sample_artifact}, address=Address.parse(":provided")),
        MockTarget({}, address=Address.parse(":not_provided")),
    ]
    stdout, _ = run_goal(targets, show_provides=True)
    assert stdout.strip() == f"//:provided {sample_artifact}"
