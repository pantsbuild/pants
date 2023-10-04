# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).
from __future__ import annotations

import os
import textwrap
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent

import pytest

from pants.base.specs import DirGlobSpec, DirLiteralSpec, FileLiteralSpec, RawSpecs, Specs
from pants.core.goals import tailor
from pants.core.goals.tailor import (
    AllOwnedSources,
    DisjointSourcePutativeTarget,
    EditBuildFilesRequest,
    EditedBuildFiles,
    PutativeTarget,
    PutativeTargets,
    PutativeTargetsRequest,
    TailorGoal,
    TailorSubsystem,
    UniquelyNamedPutativeTargets,
    default_sources_for_target_type,
    has_source_or_sources_field,
    make_content_str,
    resolve_specs_with_build,
)
from pants.core.util_rules import source_files
from pants.engine.fs import DigestContents, FileContent, PathGlobs, Paths
from pants.engine.internals.build_files import extract_build_file_options
from pants.engine.rules import Get, QueryRule, rule
from pants.engine.target import MultipleSourcesField, Target
from pants.engine.unions import UnionRule
from pants.source.filespec import FilespecMatcher
from pants.testutil.option_util import create_goal_subsystem
from pants.testutil.pytest_util import no_exception
from pants.testutil.rule_runner import RuleRunner
from pants.util.dirutil import group_by_dir
from pants.util.strutil import softwrap


class MockPutativeTargetsRequest:
    def __init__(self, dirs: tuple[str, ...], deprecated_recursive_dirs: tuple[str, ...]):
        assert dirs == ("",)
        assert not deprecated_recursive_dirs


class FortranSources(MultipleSourcesField):
    expected_file_extensions = (".f90",)


class FortranTestsSources(FortranSources):
    default = ("*_test.f90", "test_*.f90")


class FortranLibrarySources(FortranSources):
    default = ("*.f90",) + tuple(f"!{pat}" for pat in FortranTestsSources.default)


class FortranLibraryTarget(Target):
    alias = "fortran_library"
    core_fields = (FortranLibrarySources,)


class FortranTestsTarget(Target):
    alias = "fortran_tests"
    core_fields = (FortranTestsSources,)


class PutativeFortranTargetsRequest(PutativeTargetsRequest):
    pass


@rule
async def find_fortran_targets(
    req: PutativeFortranTargetsRequest, all_owned_sources: AllOwnedSources
) -> PutativeTargets:
    all_fortran_files = await Get(Paths, PathGlobs, req.path_globs("*.f90"))
    unowned_shell_files = set(all_fortran_files.files) - set(all_owned_sources)

    tests_filespec_matcher = FilespecMatcher(FortranTestsSources.default, ())
    test_filenames = set(
        tests_filespec_matcher.matches([os.path.basename(path) for path in unowned_shell_files])
    )
    test_files = {path for path in unowned_shell_files if os.path.basename(path) in test_filenames}
    sources_files = set(unowned_shell_files) - test_files
    classified_unowned_shell_files = {
        FortranTestsTarget: test_files,
        FortranLibraryTarget: sources_files,
    }

    pts = []
    for tgt_type, paths in classified_unowned_shell_files.items():
        for dirname, filenames in group_by_dir(paths).items():
            name = "tests" if tgt_type == FortranTestsTarget else None
            pts.append(
                PutativeTarget.for_target_type(
                    tgt_type, path=dirname, name=name, triggering_sources=sorted(filenames)
                )
            )
    return PutativeTargets(pts)


# This target intentionally has no `sources` field in order to test how `tailor` interacts with
# targets that have no sources. An example of this type of target is `GoExternalModule`.
class FortranModule(Target):
    alias = "fortran_module"
    core_fields = ()


@dataclass(frozen=True)
class MockPutativeFortranModuleRequest(PutativeTargetsRequest):
    pass


@rule
def infer_fortran_module_dependency(_request: MockPutativeFortranModuleRequest) -> PutativeTargets:
    return PutativeTargets(
        [
            PutativeTarget.for_target_type(
                FortranModule, path="dir", name=None, triggering_sources=[]
            )
        ]
    )


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            *tailor.rules(),
            *source_files.rules(),
            extract_build_file_options,
            find_fortran_targets,
            infer_fortran_module_dependency,
            UnionRule(PutativeTargetsRequest, PutativeFortranTargetsRequest),
            QueryRule(PutativeTargets, (MockPutativeFortranModuleRequest,)),
            QueryRule(UniquelyNamedPutativeTargets, (PutativeTargets,)),
            QueryRule(DisjointSourcePutativeTarget, (PutativeTarget,)),
            QueryRule(EditedBuildFiles, (EditBuildFilesRequest,)),
            QueryRule(AllOwnedSources, ()),
        ],
        target_types=[FortranLibraryTarget, FortranTestsTarget],
    )


def test_default_sources_for_target_type() -> None:
    assert default_sources_for_target_type(FortranLibraryTarget) == FortranLibrarySources.default
    assert default_sources_for_target_type(FortranTestsTarget) == FortranTestsSources.default
    assert default_sources_for_target_type(FortranModule) == tuple()


def test_has_source_or_sources_field() -> None:
    assert has_source_or_sources_field(FortranLibraryTarget)
    assert has_source_or_sources_field(FortranTestsTarget)
    assert not has_source_or_sources_field(FortranModule)


def test_make_content_str() -> None:
    content = make_content_str(
        "fortran_library()\n",
        "    ",
        [
            PutativeTarget.for_target_type(
                FortranTestsTarget,
                path="path/to",
                name="tests",
                triggering_sources=["test1.f90", "test2.f90"],
                kwargs={"sources": ("test1.f90", "test2.f90")},
            )
        ],
    )
    assert (
        dedent(
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
                )
            ]
        )
        == ptgts
    )


def test_root_targets_are_explicitly_named(rule_runner: RuleRunner) -> None:
    rule_runner.write_files({"foo.f90": ""})
    ptgt = PutativeTarget("", "", "fortran_library", ["foo.f90"], FortranLibrarySources.default)
    unpts = rule_runner.request(UniquelyNamedPutativeTargets, [PutativeTargets([ptgt])])
    ptgts = unpts.putative_targets
    assert (
        PutativeTargets(
            [
                PutativeTarget(
                    "",
                    "root",
                    "fortran_library",
                    ["foo.f90"],
                    FortranLibrarySources.default,
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
        "#   - src/fortran/foo/bar:bar",
        "#   - src/fortran/foo:foo",
    ) == ptgt.comments


@pytest.mark.parametrize("name", ["BUILD", "BUILD2"])
def test_edit_build_files(rule_runner: RuleRunner, name: str) -> None:
    rule_runner.write_files({f"src/fortran/foo/{name}": 'fortran_library(sources=["bar1.f90"])'})
    rule_runner.create_dir(f"src/fortran/baz/{name}")  # NB: A directory, not a file.
    req = EditBuildFilesRequest(
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    FortranTestsTarget,
                    "src/fortran/foo",
                    "tests",
                    ["bar1_test.f90"],
                    kwargs={"life_the_universe_and_everything": 42},
                ),
                PutativeTarget.for_target_type(
                    FortranLibraryTarget,
                    "src/fortran/foo",
                    "foo0",
                    ["bar2.f90", "bar3.f90"],
                    kwargs={"sources": ("bar2.f90", "bar3.f90")},
                    comments=["# A comment spread", "# over multiple lines."],
                ),
                PutativeTarget.for_target_type(
                    FortranLibraryTarget, "src/fortran/baz", "baz", ["qux1.f90"]
                ),
            ]
        ),
    )
    rule_runner.set_options(
        [
            f"--tailor-build-file-name={name}",
            "--tailor-build-file-header=Copyright © 2021 FooCorp.",
        ]
    )
    edited_build_files = rule_runner.request(EditedBuildFiles, [req])

    assert edited_build_files.created_paths == (f"src/fortran/baz/{name}.pants",)
    assert edited_build_files.updated_paths == (f"src/fortran/foo/{name}",)

    contents = rule_runner.request(DigestContents, [edited_build_files.digest])
    expected = [
        FileContent(
            f"src/fortran/baz/{name}.pants",
            dedent(
                """\
            Copyright © 2021 FooCorp.

            fortran_library()
            """
            ).encode(),
        ),
        FileContent(
            f"src/fortran/foo/{name}",
            textwrap.dedent(
                """\
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
            ).encode(),
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


def test_edit_build_files_without_header_text(rule_runner: RuleRunner) -> None:
    rule_runner.create_dir("src/fortran/baz/BUILD")  # NB: A directory, not a file.
    req = EditBuildFilesRequest(
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    FortranLibraryTarget, "src/fortran/baz", "baz", ["qux1.f90"]
                ),
            ]
        ),
    )
    edited_build_files = rule_runner.request(EditedBuildFiles, [req])

    assert edited_build_files.created_paths == ("src/fortran/baz/BUILD.pants",)

    contents = rule_runner.request(DigestContents, [edited_build_files.digest])
    expected = [
        FileContent(
            "src/fortran/baz/BUILD.pants",
            dedent(
                """\
               fortran_library()
               """
            ).encode(),
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


@pytest.mark.parametrize("header", [None, "I am some header text"])
def test_build_file_lacks_leading_whitespace(rule_runner: RuleRunner, header: str | None) -> None:
    rule_runner.create_dir("src/fortran/baz/BUILD")  # NB: A directory, not a file.
    req = EditBuildFilesRequest(
        PutativeTargets(
            [
                PutativeTarget.for_target_type(
                    FortranLibraryTarget, "src/fortran/baz", "baz", ["qux1.f90"]
                ),
            ]
        ),
    )
    if header:
        rule_runner.set_options([f"--tailor-build-file-header={header}"])
    edited_build_files = rule_runner.request(EditedBuildFiles, [req])

    assert edited_build_files.created_paths == ("src/fortran/baz/BUILD.pants",)

    contents = rule_runner.request(DigestContents, [edited_build_files.digest])
    actual = list(contents)
    # We do these more laborious asserts instead of just comparing the lists so that
    # on a text mismatch we see the actual string diff on the decoded strings.
    for afc in actual:
        content = afc.content.decode()
        assert content.lstrip() == content


def test_tailor_rule_write_mode(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "foo/bar1_test.f90": "",
            "foo/BUILD": "fortran_library()",
            "baz/qux1.f90": "",
            "conflict/f1.f90": "",
            "conflict/f2.f90": "",
            "conflict/BUILD": "fortran_library(sources=['f1.f90'])",
        }
    )
    result = rule_runner.run_goal_rule(
        TailorGoal, args=["--alias-mapping={'fortran_library': 'my_fortran_lib'}", "::"]
    )
    assert result.exit_code == 0
    assert result.stdout == dedent(
        """\
        Created baz/BUILD:
          - Add my_fortran_lib target baz
        Updated conflict/BUILD:
          - Add my_fortran_lib target conflict0
        Updated foo/BUILD:
          - Add fortran_tests target tests
        """
    )
    assert Path(rule_runner.build_root, "foo/BUILD").read_text() == dedent(
        """\
        fortran_library()

        fortran_tests(
            name="tests",
        )
        """
    )
    assert Path(rule_runner.build_root, "baz/BUILD").read_text() == "my_fortran_lib()\n"
    assert Path(rule_runner.build_root, "conflict/BUILD").read_text() == dedent(
        """\
        fortran_library(sources=['f1.f90'])

        # NOTE: Sources restricted from the default for my_fortran_lib due to conflict with
        #   - conflict:conflict
        my_fortran_lib(
            name="conflict0",
            sources=[
                "f2.f90",
            ],
        )
        """
    )


def test_tailor_rule_check_mode(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {"foo/bar1_test.f90": "", "foo/BUILD": "fortran_library()", "baz/qux1.f90": ""}
    )
    result = rule_runner.run_goal_rule(
        TailorGoal, global_args=["--pants-bin-name=./custom_pants"], args=["--check", "::"]
    )
    assert result.exit_code == 1
    assert result.stdout == dedent(
        """\
        Would create baz/BUILD:
          - Add fortran_library target baz
        Would update foo/BUILD:
          - Add fortran_tests target tests

        To fix `tailor` failures, run `./custom_pants tailor`.
        """
    )
    assert Path(rule_runner.build_root, "foo/BUILD").read_text() == "fortran_library()"
    assert not Path(rule_runner.build_root, "baz/BUILD").exists()


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
        PutativeTargets, [MockPutativeFortranModuleRequest(("dir",))]
    )
    assert putative_targets == PutativeTargets(
        [PutativeTarget.for_target_type(FortranModule, "dir", "dir", [])]
    )

    with pytest.raises(AssertionError) as excinfo:
        _ = PutativeTarget.for_target_type(FortranModule, "dir", "dir", ["a.f90"])
    expected_msg = softwrap(
        """
        A target of type FortranModule was proposed at address dir:dir with explicit sources a.f90,
        but this target type does not have a `source` or `sources` field.
        """
    )
    assert str(excinfo.value) == expected_msg


@pytest.mark.parametrize(
    "include,file_name,raises",
    (
        ("BUILD", "BUILD", False),
        ("BUILD.*", "BUILD.foo", False),
        ("BUILD.foo", "BUILD", True),
    ),
)
def test_validate_build_file_name(include: str, file_name: str, raises: bool) -> None:
    tailor_subsystem = create_goal_subsystem(TailorSubsystem, build_file_name=file_name)
    if raises:
        with pytest.raises(ValueError):
            tailor_subsystem.validate_build_file_name((include,))
    else:
        with no_exception():
            tailor_subsystem.validate_build_file_name((include,))


def test_filter_by_ignores() -> None:
    tailor_subsystem = create_goal_subsystem(
        TailorSubsystem,
        build_file_name="BUILD",
        ignore_paths=["path_ignore/**", "path_ignore_not_recursive/BUILD", "path_ignore_unused/*"],
        ignore_adding_targets=["project:bad", "//:bad", "unused:t"],
    )

    def make_ptgt(path: str, name: str) -> PutativeTarget:
        return PutativeTarget(
            path=path,
            name=name,
            type_alias="some_tgt",
            triggering_sources=[],
            owned_sources=[],
        )

    valid_ptgts = [
        make_ptgt("", "good"),
        make_ptgt("project", "good"),
        make_ptgt("path_ignore_not_recursive/subdir", "t"),
        make_ptgt("global_build_ignore_not_recursive/subdir", "t"),
    ]
    ignored_ptgts = [
        make_ptgt("", "bad"),
        make_ptgt("project", "bad"),
        make_ptgt("path_ignore", "t"),
        make_ptgt("path_ignore/subdir", "t"),
        make_ptgt("path_ignore_not_recursive", "t"),
        make_ptgt("global_build_ignore", "t"),
        make_ptgt("global_build_ignore/subdir", "t"),
        make_ptgt("global_build_ignore_not_recursive", "t"),
    ]
    result = tailor_subsystem.filter_by_ignores(
        [*valid_ptgts, *ignored_ptgts],
        build_file_ignores=(
            "global_build_ignore/**",
            "global_build_ignore_not_recursive/BUILD",
            "global_unused/*",
        ),
    )
    assert set(result) == set(valid_ptgts)


@pytest.mark.parametrize("build_file_name", ["BUILD", "OTHER_NAME"])
def test_resolve_specs_targetting_build_files(build_file_name) -> None:
    specs = Specs(
        includes=RawSpecs(
            description_of_origin="CLI arguments",
            dir_literals=(DirLiteralSpec(f"src/{build_file_name}"), DirLiteralSpec("src/dir")),
            dir_globs=(DirGlobSpec("src/other/"),),
            file_literals=(FileLiteralSpec(f"src/exists/{build_file_name}.suffix"),),
        ),
        ignores=RawSpecs(
            description_of_origin="CLI arguments",
            dir_literals=(DirLiteralSpec(f"bad/{build_file_name}"), DirLiteralSpec("bad/dir")),
            dir_globs=(DirGlobSpec("bad/other/"),),
            file_literals=(FileLiteralSpec(f"bad/exists/{build_file_name}.suffix"),),
        ),
    )
    build_file_patterns = (build_file_name, f"{build_file_name}.*")
    resolved = resolve_specs_with_build(specs, build_file_patterns)

    assert resolved.includes.file_literals == tuple()
    assert resolved.ignores.file_literals == tuple()

    assert resolved.includes.dir_literals == (
        DirLiteralSpec("src/exists"),
        DirLiteralSpec("src"),
        DirLiteralSpec("src/dir"),
    )
    assert resolved.ignores.dir_literals == (
        DirLiteralSpec("bad/exists"),
        DirLiteralSpec("bad"),
        DirLiteralSpec("bad/dir"),
    )

    assert resolved.includes.dir_globs == (
        DirGlobSpec("src/other/"),
    ), "did not passthrough other spec type"
    assert resolved.ignores.dir_globs == (
        DirGlobSpec("bad/other/"),
    ), "did not passthrough other spec type"
