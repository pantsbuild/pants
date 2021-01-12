# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap

import pytest

from pants.base.specs import AddressSpecs
from pants.build_graph.address import Address
from pants.core.goals import init
from pants.core.goals.init import (
    EditBuildFilesRequest,
    EditedBuildFiles,
    InitSubsystem,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
)
from pants.core.util_rules import source_files
from pants.engine.fs import EMPTY_DIGEST, DigestContents, FileContent, Workspace
from pants.engine.rules import QueryRule
from pants.engine.target import Target, Targets
from pants.engine.unions import UnionMembership
from pants.testutil.option_util import create_goal_subsystem
from pants.testutil.rule_runner import MockConsole, MockGet, RuleRunner, run_rule_with_mocks


class MockPutativeTargetsRequest(PutativeTargetsRequest):
    pass


class MockFortranLibrary(Target):
    alias = "fortran_library"
    core_fields = tuple()  # type: ignore[var-annotated]


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *init.rules(),
            *source_files.rules(),
            QueryRule(EditedBuildFiles, (EditBuildFilesRequest,)),
        ],
    )


def test_edit_build_files(rule_runner: RuleRunner) -> None:
    dir_structure = {
        "src/fortran/foo/BUILD": "fortran_library()",
        "src/fortran/foo/bar1.f90": "",
        "src/fortran/foo/bar1_test.f90": "",
        "src/fortran/baz/qux1.f90": "",
    }

    for path, content in dir_structure.items():
        rule_runner.create_file(path, content)

    req = EditBuildFilesRequest(
        PutativeTargets(
            [
                PutativeTarget(
                    "src/fortran/foo",
                    "tests",
                    "fortran_tests",
                    ["bar1_test.f90"],
                    kwargs={"name": "tests", "life_the_universe_and_everything": 42},
                ),
                PutativeTarget("src/fortran/baz", "baz", "fortran_library", ["qux1.f90"]),
            ]
        )
    )
    edited_build_files = rule_runner.request(EditedBuildFiles, [req])

    assert edited_build_files.created_paths == ("src/fortran/baz/BUILD",)
    assert edited_build_files.updated_paths == ("src/fortran/foo/BUILD",)

    contents = rule_runner.request(DigestContents, [edited_build_files.digest])
    expected = DigestContents(
        [
            FileContent("src/fortran/baz/BUILD", "fortran_library()\n".encode()),
            FileContent(
                "src/fortran/foo/BUILD",
                textwrap.dedent(
                    """
                fortran_library()

                fortran_tests(
                  name='tests',
                  life_the_universe_and_everything=42,
                )
                """
                )
                .lstrip()
                .encode(),
            ),
        ]
    )
    assert expected == contents


def test_init_rule(rule_runner: RuleRunner) -> None:
    console = MockConsole(use_colors=False)
    workspace = Workspace(rule_runner.scheduler)
    union_membership = UnionMembership({PutativeTargetsRequest: [MockPutativeTargetsRequest]})
    run_rule_with_mocks(
        init.init,
        rule_args=[
            create_goal_subsystem(InitSubsystem, sep="\n", output_file=None),
            console,
            workspace,
            union_membership,
        ],
        mock_gets=[
            MockGet(
                output_type=PutativeTargets,
                input_type=PutativeTargetsRequest,
                mock=lambda req: PutativeTargets(
                    [
                        PutativeTarget(
                            "src/fortran/foo", "tests", "fortran_tests", ["bar1_test.f90"]
                        ),
                        PutativeTarget("src/fortran/baz", "baz", "fortran_library", ["qux1.f90"]),
                        PutativeTarget(
                            "src/fortran/conflict",
                            "conflict",
                            "fortran_library",
                            ["conflict1.f90", "conflict2.f90"],
                        ),
                    ]
                ),
            ),
            MockGet(
                output_type=Targets,
                input_type=AddressSpecs,
                mock=lambda specs: Targets(
                    [
                        MockFortranLibrary(
                            {}, address=Address("src/fortran/foo", target_name="foo")
                        ),
                        MockFortranLibrary(
                            {}, address=Address("src/fortran/conflict", target_name="conflict")
                        ),
                    ]
                ),
            ),
            MockGet(
                output_type=EditedBuildFiles,
                input_type=EditBuildFilesRequest,
                mock=lambda _: EditedBuildFiles(
                    # We test that the created digest contains what we expect above, and we
                    # don't need to test here that writing digests to the Workspace works.
                    # So the empty digest is sufficient.
                    digest=EMPTY_DIGEST,
                    created_paths=("src/fortran/baz/BUILD",),
                    updated_paths=("src/fortran/foo/BUILD",),
                ),
            ),
        ],
        union_membership=union_membership,
    )

    stdout_str = console.stdout.getvalue()

    assert (
        "Created src/fortran/baz/BUILD:\n  - Added fortran_library target src/fortran/baz:baz"
        in stdout_str
    )
    assert (
        "Updated src/fortran/foo/BUILD:\n  - Added fortran_tests target src/fortran/foo:tests"
        in stdout_str
    )
    assert (
        "Edit src/fortran/conflict/BUILD:\n  - Add a fortran_library target for these "
        "sources: conflict1.f90, conflict2.f90"
    ) in stdout_str
