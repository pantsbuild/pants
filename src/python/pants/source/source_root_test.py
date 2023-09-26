# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from pathlib import PurePath
from typing import Iterable, Optional

import pytest

from pants.engine.fs import PathGlobs, Paths
from pants.engine.rules import QueryRule
from pants.source.source_root import (
    OptionalSourceRoot,
    SourceRoot,
    SourceRootConfig,
    SourceRootRequest,
    SourceRootsRequest,
    SourceRootsResult,
    all_roots,
    get_optional_source_root,
)
from pants.source.source_root import rules as source_root_rules
from pants.testutil.option_util import create_subsystem
from pants.testutil.rule_runner import MockGet, RuleRunner, run_rule_with_mocks


def _find_root(
    path: str,
    patterns: Iterable[str],
    marker_filenames: Optional[Iterable[str]] = None,
    existing_marker_files: Optional[Iterable[str]] = None,
) -> Optional[str]:
    source_root_config = create_subsystem(
        SourceRootConfig,
        root_patterns=list(patterns),
        marker_filenames=list(marker_filenames or []),
    )

    # This inner function is passed as the callable to the mock, to allow recursion in the rule.
    def _mock_fs_check(pathglobs: PathGlobs) -> Paths:
        for glob in pathglobs.globs:
            if glob in (existing_marker_files or []):
                d, f = os.path.split(pathglobs.globs[0])
                return Paths(files=(f,), dirs=(d,))
        return Paths(files=tuple(), dirs=tuple())

    def _do_find_root(src_root_req: SourceRootRequest) -> OptionalSourceRoot:
        return run_rule_with_mocks(
            get_optional_source_root,
            rule_args=[src_root_req, source_root_config],
            mock_gets=[
                MockGet(
                    output_type=OptionalSourceRoot,
                    input_types=(SourceRootRequest,),
                    mock=_do_find_root,
                ),
                MockGet(output_type=Paths, input_types=(PathGlobs,), mock=_mock_fs_check),
            ],
        )

    source_root = _do_find_root(SourceRootRequest(PurePath(path))).source_root
    return None if source_root is None else source_root.path


def test_source_root_at_buildroot() -> None:
    def find_root(path):
        return _find_root(path, ("/",))

    assert "." == find_root("foo/bar.py")
    assert "." == find_root("foo/")
    assert "." == find_root("foo")
    with pytest.raises(ValueError, match="cannot contain `..` segment: ../foo/bar.py"):
        find_root("../foo/bar.py")


def test_fixed_source_roots() -> None:
    def find_root(path):
        return _find_root(path, ("/root1", "/foo/root2", "/root1/root3"))

    assert "root1" == find_root("root1/bar.py")
    assert "foo/root2" == find_root("foo/root2/bar/baz.py")
    assert "root1/root3" == find_root("root1/root3/qux.py")
    assert "root1/root3" == find_root("root1/root3/qux/quux.py")
    assert "root1/root3" == find_root("root1/root3")
    assert find_root("blah/blah.py") is None


def test_source_root_suffixes() -> None:
    def find_root(path):
        return _find_root(path, ("src/python", "/"))

    assert "src/python" == find_root("src/python/foo/bar.py")
    assert "src/python/foo/src/python" == find_root("src/python/foo/src/python/bar.py")
    assert "." == find_root("foo/bar.py")


def test_source_root_patterns() -> None:
    def find_root(path):
        return _find_root(path, ("src/*", "/project/*"))

    assert "src/python" == find_root("src/python/foo/bar.py")
    assert "src/python/foo/src/shell" == find_root("src/python/foo/src/shell/bar.sh")
    assert "project/python" == find_root("project/python/foo/bar.py")
    assert find_root("prefix/project/python/foo/bar.py") is None


def test_source_root_default_patterns() -> None:
    # Test that the default root patterns behave as expected.
    def find_root(path):
        return _find_root(path, tuple(SourceRootConfig.DEFAULT_ROOT_PATTERNS))

    assert "src/python" == find_root("src/python/foo/bar.py")
    assert "src" == find_root("src/baz/qux.py")
    assert "project1/src/python" == find_root("project1/src/python/foo/bar.py")
    assert "project2/src" == find_root("project2/src/baz/qux.py")
    assert "." == find_root("corge/grault.py")


def test_marker_file() -> None:
    def find_root(path):
        return _find_root(
            path,
            tuple(),
            ("SOURCE_ROOT",),
            (
                "project1/SOURCE_ROOT",
                "project2/src/SOURCE_ROOT",
            ),
        )

    assert "project1" == find_root("project1/foo/bar.py")
    assert "project1" == find_root("project1/foo/")
    assert "project1" == find_root("project1/foo")
    assert "project1" == find_root("project1/")
    assert "project1" == find_root("project1")
    assert "project2/src" == find_root("project2/src/baz/qux.py")
    assert "project2/src" == find_root("project2/src/baz/")
    assert "project2/src" == find_root("project2/src/baz")
    assert "project2/src" == find_root("project2/src/")
    assert "project2/src" == find_root("project2/src")
    assert find_root("project3/qux") is None
    assert find_root("project3/") is None
    assert find_root("project3") is None


def test_marker_file_nested_source_roots() -> None:
    def find_root(path):
        return _find_root(
            path,
            tuple(),
            ("SOURCE_ROOT",),
            (
                "SOURCE_ROOT",
                "project1/src/SOURCE_ROOT",
            ),
        )

    assert "project1/src" == find_root("project1/src/foo/bar.py")
    assert "project1/src" == find_root("project1/src/foo")
    assert "project1/src" == find_root("project1/src")
    assert "." == find_root("project1")
    assert "." == find_root("baz/qux.py")
    assert "." == find_root("baz")
    assert "." == find_root(".")
    assert "." == find_root("")


def test_multiple_marker_filenames() -> None:
    def find_root(path):
        return _find_root(
            path,
            tuple(),
            ("SOURCE_ROOT", "setup.py"),
            (
                "project1/javasrc/SOURCE_ROOT",
                "project2/setup.py",
            ),
        )

    assert "project1/javasrc" == find_root("project1/javasrc/foo/bar.java")
    assert "project2" == find_root("project2/foo/bar.py")


def test_marker_file_and_patterns() -> None:
    def find_root(path):
        return _find_root(path, ("src/python",), ("setup.py",), ("project1/setup.py",))

    assert "project1" == find_root("project1/foo/bar.py")
    assert "project2/src/python" == find_root("project2/src/python/baz/qux.py")


def test_all_roots() -> None:
    dirs = (
        "contrib/go/examples/src/go/src",
        "src/java",
        "src/python",
        "src/python/subdir/src/python",  # We allow source roots under source roots.
        "src/kotlin",
        "my/project/src/java",
        "src/example/java",
        "src/example/python",
        "fixed/root/jvm",
    )

    source_root_config = create_subsystem(
        SourceRootConfig,
        root_patterns=[
            "src/*",
            "src/example/*",
            "contrib/go/examples/src/go/src",
            # Dir does not exist, should not be listed as a root.
            "java",
            "fixed/root/jvm",
        ],
        marker_filenames=[],
    )

    # This function mocks out reading real directories off the file system.
    def provider_rule(_: PathGlobs) -> Paths:
        return Paths((), dirs)

    def source_root_mock_rule(req: SourceRootRequest) -> OptionalSourceRoot:
        for d in dirs:
            if str(req.path).startswith(d):
                return OptionalSourceRoot(SourceRoot(str(req.path)))
        return OptionalSourceRoot(None)

    output = run_rule_with_mocks(
        all_roots,
        rule_args=[source_root_config],
        mock_gets=[
            MockGet(output_type=Paths, input_types=(PathGlobs,), mock=provider_rule),
            MockGet(
                output_type=OptionalSourceRoot,
                input_types=(SourceRootRequest,),
                mock=source_root_mock_rule,
            ),
        ],
    )

    assert {
        SourceRoot("contrib/go/examples/src/go/src"),
        SourceRoot("src/java"),
        SourceRoot("src/python"),
        SourceRoot("src/python/subdir/src/python"),
        SourceRoot("src/kotlin"),
        SourceRoot("src/example/java"),
        SourceRoot("src/example/python"),
        SourceRoot("my/project/src/java"),
        SourceRoot("fixed/root/jvm"),
    } == set(output)


def test_all_roots_with_root_at_buildroot() -> None:
    source_root_config = create_subsystem(
        SourceRootConfig,
        root_patterns=["/"],
        marker_filenames=[],
    )

    # This function mocks out reading real directories off the file system
    def provider_rule(_: PathGlobs) -> Paths:
        dirs = ("foo",)  # A python package at the buildroot.
        return Paths((), dirs)

    output = run_rule_with_mocks(
        all_roots,
        rule_args=[source_root_config],
        mock_gets=[
            MockGet(output_type=Paths, input_types=(PathGlobs,), mock=provider_rule),
            MockGet(
                output_type=OptionalSourceRoot,
                input_types=(SourceRootRequest,),
                mock=lambda req: OptionalSourceRoot(SourceRoot(".")),
            ),
        ],
    )
    assert {SourceRoot(".")} == set(output)


def test_source_roots_request() -> None:
    rule_runner = RuleRunner(
        rules=[
            *source_root_rules(),
            QueryRule(SourceRootsResult, (SourceRootsRequest,)),
        ]
    )
    rule_runner.set_options(["--source-root-patterns=['src/python','tests/python']"])
    req = SourceRootsRequest(
        files=(PurePath("src/python/foo/bar.py"), PurePath("tests/python/foo/bar_test.py")),
        dirs=(PurePath("src/python/foo"), PurePath("src/python/baz/qux")),
    )
    res = rule_runner.request(SourceRootsResult, [req])
    assert {
        PurePath("src/python/foo/bar.py"): SourceRoot("src/python"),
        PurePath("tests/python/foo/bar_test.py"): SourceRoot("tests/python"),
        PurePath("src/python/foo"): SourceRoot("src/python"),
        PurePath("src/python/baz/qux"): SourceRoot("src/python"),
    } == dict(res.path_to_root)
