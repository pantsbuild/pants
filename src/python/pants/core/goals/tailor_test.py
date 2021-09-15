# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import textwrap
from dataclasses import dataclass

import pytest

from pants.base.specs import (
    AddressLiteralSpec,
    AddressSpecs,
    FilesystemLiteralSpec,
    FilesystemSpecs,
    Specs,
)
from pants.core.goals import tailor
from pants.core.goals.tailor import (
    AllOwnedSources,
    DisjointSourcePutativeTarget,
    EditBuildFilesRequest,
    EditedBuildFiles,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
    PutativeTargetsSearchPaths,
    TailorSubsystem,
    UniquelyNamedPutativeTargets,
    default_sources_for_target_type,
    group_by_dir,
    make_content_str,
    specs_to_dirs,
)
from pants.core.util_rules import source_files
from pants.engine.fs import EMPTY_DIGEST, DigestContents, FileContent, Workspace
from pants.engine.rules import QueryRule, rule
from pants.engine.target import Sources, Target
from pants.engine.unions import UnionMembership, UnionRule
from pants.testutil.option_util import create_goal_subsystem
from pants.testutil.rule_runner import MockGet, RuleRunner, mock_console, run_rule_with_mocks


class MockPutativeTargetsRequest:
    def __init__(self, search_paths: PutativeTargetsSearchPaths):
        assert search_paths.dirs == ("",)


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


# This target intentionally has no `sources` field in order to test how `tailor` interacts with targets that
# have no sources. An example of this type of target is `GoExternalModule`.
class FortranModule(Target):
    alias = "fortran_module"
    core_fields = ()


@dataclass(frozen=True)
class MockPutativeFortranModuleRequest(PutativeTargetsRequest):
    pass


@rule
def find_fortran_module(_request: MockPutativeFortranModuleRequest) -> PutativeTargets:
    return PutativeTargets(
        [
            PutativeTarget.for_target_type(
                FortranModule, path="dir", name="mod", triggering_sources=[]
            )
        ]
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            *source_files.rules(),
            find_fortran_module,
            UnionRule(PutativeTargetsRequest, MockPutativeFortranModuleRequest),
            QueryRule(PutativeTargets, (MockPutativeFortranModuleRequest,)),
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
    assert default_sources_for_target_type(FortranModule) == tuple()


def test_make_content_str() -> None:
    content = make_content_str(
        "fortran_library()\n",
        "    ",
        [
            PutativeTarget.for_target_type(
                FortranTests,
                path="path/to",
                name="tests",
                triggering_sources=["test1.f90", "test2.f90"],
                kwargs={"sources": ("test1.f90", "test2.f90")},
            )
        ],
    )
    assert (
        textwrap.dedent(
            """\
            fortran_library()

            fortran_tests(
                name="tests",
                sources=[
                    "test1.f90",
                    "test2.f90",
                ],
            )
            """
        )
        == content
    )


def test_make_content_str_for_old_style_macro() -> None:
    content = make_content_str(
        "fortran_library()\n",
        "    ",
        [
            PutativeTarget(
                path="path/to",
                name=None,
                type_alias="fortran_macro",
                triggering_sources=[],
                owned_sources=[],
                kwargs={},
            )
        ],
    )
    assert (
        textwrap.dedent(
            """
            fortran_library()

            fortran_macro()
            """
        ).lstrip()
        == content
    )


def test_rename_conflicting_targets(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/fortran/foo/BUILD": "fortran_library(sources=['bar1.f90'])\n"
            "fortran_library(name='foo0', sources=['bar2.f90'])",
            "src/fortran/foo/bar1.f90": "",
            "src/fortran/foo/bar2.f90": "",
            "src/fortran/foo/bar3.f90": "",
        }
    )
    ptgt = PutativeTarget(
        path="src/fortran/foo",
        name="foo",
        type_alias="fortran_library",
        triggering_sources=["bar3.f90"],
        owned_sources=FortranLibrarySources.default,
    )
    unpts = rule_runner.request(UniquelyNamedPutativeTargets, [PutativeTargets([ptgt])])
    ptgts = unpts.putative_targets
    assert (
        PutativeTargets(
            [
                PutativeTarget(
                    path="src/fortran/foo",
                    name="foo1",
                    type_alias="fortran_library",
                    triggering_sources=["bar3.f90"],
                    owned_sources=FortranLibrarySources.default,
                )
            ]
        )
        == ptgts
    )


def test_restrict_conflicting_sources(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "src/fortran/foo/BUILD": "fortran_library(sources=['bar/baz1.f90'])",
            "src/fortran/foo/bar/BUILD": "fortran_library(sources=['baz2.f90'])",
            "src/fortran/foo/bar/baz1.f90": "",
            "src/fortran/foo/bar/baz2.f90": "",
            "src/fortran/foo/bar/baz3.f90": "",
        }
    )
    ptgt = PutativeTarget(
        path="src/fortran/foo/bar",
        name="bar0",
        type_alias="fortran_library",
        triggering_sources=["baz3.f90"],
        owned_sources=FortranLibrarySources.default,
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
    rule_runner.write_files({"src/fortran/foo/BUILD": 'fortran_library(sources=["bar1.f90"])'})
    rule_runner.create_dir("src/fortran/baz/BUILD")  # NB: A directory, not a file.
    req = EditBuildFilesRequest(
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    FortranTests,
                    path="src/fortran/foo",
                    name="tests",
                    triggering_sources=["bar1_test.f90"],
                    kwargs={"life_the_universe_and_everything": 42},
                ),
                PutativeTarget.for_target_type(
                    FortranLibrary,
                    path="src/fortran/foo",
                    name="foo0",
                    triggering_sources=["bar2.f90", "bar3.f90"],
                    kwargs={"sources": ("bar2.f90", "bar3.f90")},
                    comments=["# A comment spread", "# over multiple lines."],
                ),
                PutativeTarget.for_target_type(
                    FortranLibrary,
                    path="src/fortran/baz",
                    name="lib",
                    triggering_sources=["qux1.f90"],
                ),
            ]
        ),
        indent="    ",
    )
    edited_build_files = rule_runner.request(EditedBuildFiles, [req])

    assert edited_build_files.created_paths == ("src/fortran/baz/BUILD.pants",)
    assert edited_build_files.updated_paths == ("src/fortran/foo/BUILD",)

    contents = rule_runner.request(DigestContents, [edited_build_files.digest])
    expected = [
        FileContent(
            "src/fortran/baz/BUILD.pants",
            textwrap.dedent(
                """\
                fortran_library(
                    name="lib",
                )
                """
            ).encode(),
        ),
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


def test_group_by_dir() -> None:
    paths = {
        "foo/bar/baz1.ext",
        "foo/bar/baz1_test.ext",
        "foo/bar/qux/quux1.ext",
        "foo/__init__.ext",
        "foo/bar/__init__.ext",
        "foo/bar/baz2.ext",
        "foo/bar1.ext",
        "foo1.ext",
        "__init__.ext",
    }
    assert {
        "": {"__init__.ext", "foo1.ext"},
        "foo": {"__init__.ext", "bar1.ext"},
        "foo/bar": {"__init__.ext", "baz1.ext", "baz1_test.ext", "baz2.ext"},
        "foo/bar/qux": {"quux1.ext"},
    } == group_by_dir(paths)


def test_specs_to_dirs() -> None:
    assert specs_to_dirs(Specs(AddressSpecs([]), FilesystemSpecs([]))) == ("",)
    assert specs_to_dirs(
        Specs(AddressSpecs([AddressLiteralSpec("src/python/foo", "foo")]), FilesystemSpecs([]))
    ) == ("src/python/foo",)
    assert (
        specs_to_dirs(
            Specs(
                AddressSpecs(
                    [
                        AddressLiteralSpec("src/python/foo", "foo"),
                        AddressLiteralSpec("src/python/bar", "bar"),
                    ]
                ),
                FilesystemSpecs([]),
            )
        )
        == ("src/python/foo", "src/python/bar")
    )

    with pytest.raises(ValueError):
        specs_to_dirs(
            Specs(AddressSpecs([]), FilesystemSpecs([FilesystemLiteralSpec("src/python/foo.py")]))
        )

    with pytest.raises(ValueError):
        specs_to_dirs(
            Specs(
                AddressSpecs([AddressLiteralSpec("src/python/bar", "notbar")]), FilesystemSpecs([])
            )
        )


def test_tailor_rule(rule_runner: RuleRunner) -> None:
    with mock_console(rule_runner.options_bootstrapper) as (console, stdio_reader):
        workspace = Workspace(rule_runner.scheduler)
        union_membership = UnionMembership({PutativeTargetsRequest: [MockPutativeTargetsRequest]})
        specs = Specs(
            address_specs=AddressSpecs(tuple()), filesystem_specs=FilesystemSpecs(tuple())
        )
        run_rule_with_mocks(
            tailor.tailor,
            rule_args=[
                create_goal_subsystem(
                    TailorSubsystem,
                    build_file_indent="    ",
                    alias_mapping={"fortran_library": "my_fortran_lib"},
                ),
                console,
                workspace,
                union_membership,
                specs,
            ],
            mock_gets=[
                MockGet(
                    output_type=PutativeTargets,
                    input_type=PutativeTargetsRequest,
                    mock=lambda req: PutativeTargets(
                        [
                            PutativeTarget.for_target_type(
                                FortranTests,
                                path="src/fortran/foo",
                                name="tests",
                                triggering_sources=["bar1_test.f90"],
                            ),
                            PutativeTarget.for_target_type(
                                FortranLibrary,
                                path="src/fortran/baz",
                                name="lib",
                                triggering_sources=["qux1.f90"],
                            ),
                            PutativeTarget.for_target_type(
                                FortranLibrary,
                                path="src/fortran/conflict",
                                name="conflict",
                                triggering_sources=["conflict1.f90", "conflict2.f90"],
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

        stdout_str = stdio_reader.get_stdout()

    assert (
        "Created src/fortran/baz/BUILD:\n  - Added my_fortran_lib target src/fortran/baz:lib"
        in stdout_str
    )
    assert (
        "Updated src/fortran/foo/BUILD:\n  - Added fortran_tests target src/fortran/foo:tests"
        in stdout_str
    )
    assert (
        "Updated src/fortran/conflict/BUILD:\n  - Added my_fortran_lib target "
        "src/fortran/conflict:conflict0"
    ) in stdout_str


def test_all_owned_sources(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "dir/a.f90": "",
            "dir/b.f90": "",
            "dir/a_test.f90": "",
            "dir/unowned.txt": "",
            "dir/BUILD": "fortran_library()\nfortran_tests(name='tests')",
            "unowned.txt": "",
            "unowned.f90": "",
        }
    )
    assert rule_runner.request(AllOwnedSources, []) == AllOwnedSources(
        ["dir/a.f90", "dir/b.f90", "dir/a_test.f90"]
    )


def test_target_type_with_no_sources_field(rule_runner: RuleRunner) -> None:
    putative_targets = rule_runner.request(
        PutativeTargets,
        [MockPutativeFortranModuleRequest(PutativeTargetsSearchPaths(tuple("")))],
    )
    assert putative_targets == PutativeTargets(
        [
            PutativeTarget.for_target_type(
                FortranModule, path="dir", name="mod", triggering_sources=[]
            )
        ]
    )

    with pytest.raises(ValueError) as excinfo:
        PutativeTarget.for_target_type(
            FortranModule, path="dir", name="mod", triggering_sources=["a.f90"]
        )
    expected_msg = (
        "A target of type FortranModule was proposed at address dir:mod with explicit sources a.f90, "
        "but this target type does not have a `sources` field."
    )
    assert str(excinfo.value) == expected_msg
