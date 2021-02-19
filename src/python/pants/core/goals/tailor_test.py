# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap

import pytest

from pants.core.goals import tailor
from pants.core.goals.tailor import (
    AllOwnedSources,
    DisjointSourcePutativeTarget,
    EditBuildFilesRequest,
    EditedBuildFiles,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
    TailorSubsystem,
    UniquelyNamedPutativeTargets,
    default_sources_for_target_type,
    make_content_str,
)
from pants.core.util_rules import source_files
from pants.engine.fs import EMPTY_DIGEST, DigestContents, FileContent, Workspace
from pants.engine.rules import QueryRule
from pants.engine.target import Sources, Target
from pants.engine.unions import UnionMembership
from pants.testutil.option_util import create_goal_subsystem
from pants.testutil.rule_runner import MockConsole, MockGet, RuleRunner, run_rule_with_mocks


class MockPutativeTargetsRequest(PutativeTargetsRequest):
    pass


class FortranSources(Sources):
    expected_file_extensions = (".f90",)


class FortranTestsSources(FortranSources):
    default = ("*_test.f90", "test_*.f90")


class FortranLibrarySources(FortranSources):
    default = ("*.f90",) + tuple(f"!{pat}" for pat in FortranTestsSources.default)


class FortranLibrary(Target):
    alias = "fortran_library"
    core_fields = (FortranLibrarySources,)


class FortranTests(Target):
    alias = "fortran_tests"
    core_fields = (FortranTestsSources,)


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            *source_files.rules(),
            QueryRule(UniquelyNamedPutativeTargets, (PutativeTargets,)),
            QueryRule(DisjointSourcePutativeTarget, (PutativeTarget,)),
            QueryRule(EditedBuildFiles, (EditBuildFilesRequest,)),
            QueryRule(AllOwnedSources, ()),
        ],
        target_types=[FortranLibrary, FortranTests],
    )


def test_default_sources_for_target_type() -> None:
    assert default_sources_for_target_type(FortranLibrary) == FortranLibrarySources.default
    assert default_sources_for_target_type(FortranTests) == FortranTestsSources.default


def test_make_content_str() -> None:
    content = make_content_str(
        "fortran_library()\n",
        "    ",
        [
            PutativeTarget.for_target_type(
                FortranTests,
                "path/to",
                "tests",
                ["test1.f90", "test2.f90"],
                kwargs={"name": "tests", "sources": ("test1.f90", "test2.f90")},
            )
        ],
    )
    assert (
        textwrap.dedent(
            """
    fortran_library()

    fortran_tests(
        name="tests",
        sources=[
            "test1.f90",
            "test2.f90",
        ],
    )
    """
        ).lstrip()
        == content
    )


def test_rename_conflicting_targets(rule_runner: RuleRunner) -> None:
    dir_structure = {
        "src/fortran/foo/BUILD": "fortran_library(sources=['bar1.f90'])\n"
        "fortran_library(name='foo0', sources=['bar2.f90'])",
        "src/fortran/foo/bar1.f90": "",
        "src/fortran/foo/bar2.f90": "",
        "src/fortran/foo/bar3.f90": "",
    }

    for path, content in dir_structure.items():
        rule_runner.create_file(path, content)

    ptgt = PutativeTarget(
        "src/fortran/foo", "foo", "fortran_library", ["bar3.f90"], FortranLibrarySources.default
    )
    unpts = rule_runner.request(UniquelyNamedPutativeTargets, [PutativeTargets([ptgt])])
    ptgts = unpts.putative_targets
    assert (
        PutativeTargets(
            [
                PutativeTarget(
                    "src/fortran/foo",
                    "foo1",
                    "fortran_library",
                    ["bar3.f90"],
                    FortranLibrarySources.default,
                    kwargs={"name": "foo1"},
                )
            ]
        )
        == ptgts
    )


def test_restrict_conflicting_sources(rule_runner: RuleRunner) -> None:
    dir_structure = {
        "src/fortran/foo/BUILD": "fortran_library(sources=['bar/baz1.f90'])",
        "src/fortran/foo/bar/BUILD": "fortran_library(sources=['baz2.f90'])",
        "src/fortran/foo/bar/baz1.f90": "",
        "src/fortran/foo/bar/baz2.f90": "",
        "src/fortran/foo/bar/baz3.f90": "",
    }

    for path, content in dir_structure.items():
        rule_runner.create_file(path, content)

    ptgt = PutativeTarget(
        "src/fortran/foo/bar",
        "bar0",
        "fortran_library",
        ["baz3.f90"],
        FortranLibrarySources.default,
    )
    dspt = rule_runner.request(DisjointSourcePutativeTarget, [ptgt])
    ptgt = dspt.putative_target
    assert ("baz3.f90",) == ptgt.owned_sources
    assert ("baz3.f90",) == ptgt.kwargs.get("sources")
    assert (
        "# NOTE: Sources restricted from the default for fortran_library due to conflict with",
        "#   - src/fortran/foo",
        "#   - src/fortran/foo/bar",
    ) == ptgt.comments


def test_edit_build_files(rule_runner: RuleRunner) -> None:
    rule_runner.create_file("src/fortran/foo/BUILD", 'fortran_library(sources=["bar1.f90"])')
    req = EditBuildFilesRequest(
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    FortranTests,
                    "src/fortran/foo",
                    "tests",
                    ["bar1_test.f90"],
                    kwargs={"name": "tests", "life_the_universe_and_everything": 42},
                ),
                PutativeTarget.for_target_type(
                    FortranLibrary,
                    "src/fortran/foo",
                    "foo0",
                    ["bar2.f90", "bar3.f90"],
                    kwargs={"name": "foo0", "sources": ("bar2.f90", "bar3.f90")},
                    comments=["# A comment spread", "# over multiple lines."],
                ),
                PutativeTarget.for_target_type(
                    FortranLibrary, "src/fortran/baz", "baz", ["qux1.f90"]
                ),
            ]
        ),
        indent="    ",
    )
    edited_build_files = rule_runner.request(EditedBuildFiles, [req])

    assert edited_build_files.created_paths == ("src/fortran/baz/BUILD",)
    assert edited_build_files.updated_paths == ("src/fortran/foo/BUILD",)

    contents = rule_runner.request(DigestContents, [edited_build_files.digest])
    expected = [
        FileContent("src/fortran/baz/BUILD", "fortran_library()\n".encode()),
        FileContent(
            "src/fortran/foo/BUILD",
            textwrap.dedent(
                """
            fortran_library(sources=["bar1.f90"])

            # A comment spread
            # over multiple lines.
            fortran_library(
                name="foo0",
                sources=[
                    "bar2.f90",
                    "bar3.f90",
                ],
            )

            fortran_tests(
                name="tests",
                life_the_universe_and_everything=42,
            )
            """
            )
            .lstrip()
            .encode(),
        ),
    ]
    actual = list(contents)
    # We do these more laborious asserts instead of just comparing the lists so that
    # on a text mismatch we see the actual string diff on the decoded strings.
    assert len(expected) == len(actual)
    for efc, afc in zip(expected, actual):
        assert efc.path == afc.path
        assert efc.content.decode() == afc.content.decode()
        assert efc.is_executable == afc.is_executable


def test_tailor_rule(rule_runner: RuleRunner) -> None:
    console = MockConsole(use_colors=False)
    workspace = Workspace(rule_runner.scheduler)
    union_membership = UnionMembership({PutativeTargetsRequest: [MockPutativeTargetsRequest]})
    run_rule_with_mocks(
        tailor.tailor,
        rule_args=[
            create_goal_subsystem(TailorSubsystem, build_file_indent="    "),
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
                        PutativeTarget.for_target_type(
                            FortranTests, "src/fortran/foo", "tests", ["bar1_test.f90"]
                        ),
                        PutativeTarget.for_target_type(
                            FortranLibrary, "src/fortran/baz", "baz", ["qux1.f90"]
                        ),
                        PutativeTarget.for_target_type(
                            FortranLibrary,
                            "src/fortran/conflict",
                            "conflict",
                            ["conflict1.f90", "conflict2.f90"],
                        ),
                    ]
                ),
            ),
            MockGet(
                output_type=UniquelyNamedPutativeTargets,
                input_type=PutativeTargets,
                mock=lambda pts: UniquelyNamedPutativeTargets(
                    PutativeTargets(
                        [pt.rename("conflict0") if pt.name == "conflict" else pt for pt in pts]
                    )
                ),
            ),
            MockGet(
                output_type=DisjointSourcePutativeTarget,
                input_type=PutativeTarget,
                # This test exists to test the console output, which isn't affected by
                # whether the sources of a putative target were modified due to conflict,
                # so we don't bother to inject such modifications. The BUILD file content
                # generation, which is so affected, is tested separately above.
                mock=lambda pt: DisjointSourcePutativeTarget(pt),
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
                    updated_paths=(
                        "src/fortran/foo/BUILD",
                        "src/fortran/conflict/BUILD",
                    ),
                ),
            ),
        ],
        union_membership=union_membership,
    )

    stdout_str = console.stdout.getvalue()

    assert (
        "Created src/fortran/baz/BUILD:\n  - Added fortran_library target src/fortran/baz"
        in stdout_str
    )
    assert (
        "Updated src/fortran/foo/BUILD:\n  - Added fortran_tests target src/fortran/foo:tests"
        in stdout_str
    )
    assert (
        "Updated src/fortran/conflict/BUILD:\n  - Added fortran_library target "
        "src/fortran/conflict:conflict0"
    ) in stdout_str


def test_all_owned_sources(rule_runner: RuleRunner) -> None:
    for path in [
        "dir/a.f90",
        "dir/b.f90",
        "dir/a_test.f90",
        "dir/unowned.txt",
        "unowned.txt",
        "unowned.f90",
    ]:
        rule_runner.create_file(path)
    rule_runner.add_to_build_file("dir", "fortran_library()\nfortran_tests(name='tests')")
    assert rule_runner.request(AllOwnedSources, []) == AllOwnedSources(
        ["dir/a.f90", "dir/b.f90", "dir/a_test.f90"]
    )
