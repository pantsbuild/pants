# Copyright 2025 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pathlib import Path, PurePath

import pytest

from pants.engine.fs import PathGlobs, PathMetadataRequest, PathMetadataResult, Paths
from pants.engine.internals.native_engine import PyNgInvocation, PyNgOptions
from pants.engine.rules import QueryRule
from pants.ng.source_partition import (
    SourcePaths,
    find_common_dir,
    partition_sources,
)
from pants.source.source_root import SourceRoot, SourceRootsResult
from pants.testutil.rule_runner import RuleRunner, run_rule_with_mocks
from pants.util.contextutil import pushd
from pants.util.frozendict import FrozenDict


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[QueryRule(PathMetadataResult, (PathMetadataRequest,))],
    )


def _call_find_common_dir(rule_runner: RuleRunner, source_paths: SourcePaths) -> Path | None:
    return (
        run_rule_with_mocks(
            find_common_dir,
            rule_args=[source_paths],
            mock_calls={
                "pants.engine.intrinsics.path_metadata_request": lambda *pmr: rule_runner.request(
                    PathMetadataResult, pmr
                )
            },
        )
    ).path


def test_find_common_dir_single_file(rule_runner: RuleRunner) -> None:
    build_root = Path(rule_runner.build_root)
    source_root = SourceRoot("src/python")
    foo_dir = build_root / source_root.path / "foo"
    foo_dir.mkdir(parents=True)
    (foo_dir / "bar.py").touch()

    assert _call_find_common_dir(
        rule_runner, SourcePaths((Path("src/python/foo/bar.py"),), source_root)
    ) == Path("src/python/foo")


def test_find_common_dir_single_file_symlink(rule_runner: RuleRunner) -> None:
    build_root = Path(rule_runner.build_root)
    link_target = build_root / "dir" / "link_target.py"
    link_target.parent.mkdir(parents=True)
    link_target.touch()
    source_root = SourceRoot("src/python")
    foo_dir = build_root / source_root.path / "foo"
    foo_dir.mkdir(parents=True)
    (foo_dir / "bar.py").symlink_to(Path("..") / ".." / ".." / "dir" / "link_target.py")

    assert _call_find_common_dir(
        rule_runner, SourcePaths((Path("src/python/foo/bar.py"),), source_root)
    ) == Path("src/python/foo")


def test_find_common_dir_single_dir_symlink(rule_runner: RuleRunner) -> None:
    build_root = Path(rule_runner.build_root)
    link_target = build_root / "dir" / "link_target_dir"
    link_target.mkdir(parents=True)
    source_root = SourceRoot("src/python")
    foo_dir = build_root / source_root.path / "foo"
    foo_dir.mkdir(parents=True)
    (foo_dir / "bar").symlink_to(Path("..") / ".." / ".." / "dir" / "link_target_dir")

    assert _call_find_common_dir(
        rule_runner, SourcePaths((Path("src/python/foo/bar"),), source_root)
    ) == Path("src/python/foo/bar")


def test_find_common_dir_single_file_symlink_with_intermediate_symlink_dir(
    rule_runner: RuleRunner,
) -> None:
    build_root = Path(rule_runner.build_root)
    link_target = build_root / "p" / "q" / "link_target.py"
    link_target.parent.mkdir(parents=True)
    link_target.touch()
    source_root = SourceRoot("src/python")
    b_dir = build_root / source_root.path / "a" / "b"
    c_dir = build_root / source_root.path / "c"
    b_dir.mkdir(parents=True)
    c_dir.mkdir(parents=True)
    (b_dir / "d").symlink_to(PurePath("..") / ".." / ".." / ".." / "p")
    (c_dir / "e.py").symlink_to(PurePath("..") / "a" / "b" / "d" / "q" / "link_target.py")

    assert _call_find_common_dir(
        rule_runner, SourcePaths((Path("src/python/c/e.py"),), source_root)
    ) == Path("src/python/c")


def test_find_common_dir_single_dir(rule_runner: RuleRunner) -> None:
    build_root = Path(rule_runner.build_root)
    source_root = SourceRoot("src/python")
    foo_dir = build_root / source_root.path / "foo"
    bar_file = foo_dir / "bar.py"
    baz_file = foo_dir / "baz.py"
    foo_dir.mkdir(parents=True)
    bar_file.touch()
    baz_file.touch()

    assert _call_find_common_dir(
        rule_runner, SourcePaths((Path("src/python/foo/bar.py"),), source_root)
    ) == Path("src/python/foo")

    assert _call_find_common_dir(
        rule_runner,
        SourcePaths((Path("src/python/foo/bar.py"), Path("src/python/foo/baz.py")), source_root),
    ) == Path("src/python/foo")


def test_find_common_dir_multiple_dirs(rule_runner: RuleRunner) -> None:
    build_root = Path(rule_runner.build_root)
    source_root = SourceRoot("src/python")
    foo_dir = build_root / source_root.path / "foo"
    a_dir = foo_dir / "a"
    b_dir = foo_dir / "b"
    bar_file = a_dir / "bar.py"
    baz_file = b_dir / "baz.py"
    a_dir.mkdir(parents=True)
    b_dir.mkdir(parents=True)
    bar_file.touch()
    baz_file.touch()

    assert _call_find_common_dir(
        rule_runner,
        SourcePaths((Path("src/python/foo/bar.py"), Path("src/python/foo/baz.py")), source_root),
    ) == Path("src/python/foo")


def test_find_common_dir_deeply_nested(rule_runner: RuleRunner) -> None:
    build_root = Path(rule_runner.build_root)
    source_root = SourceRoot("src/python")
    b_dir = build_root / source_root.path / "b"
    c_dir = b_dir / "c"
    d_dir = b_dir / "d"
    e_dir = c_dir / "e"
    bar_file = c_dir / "bar.py"
    baz_file = d_dir / "baz.py"
    qux_file = e_dir / "qux.py"

    for d in b_dir, c_dir, d_dir, e_dir:
        d.mkdir(parents=True)
    for f in bar_file, baz_file, qux_file:
        f.touch()

    assert _call_find_common_dir(
        rule_runner,
        SourcePaths((Path("src/python/b/c/bar.py"), Path("src/python/b/d/baz.py")), source_root),
    ) == Path("src/python/b")

    assert _call_find_common_dir(
        rule_runner,
        SourcePaths((Path("src/python/b/c/bar.py"), Path("src/python/b/c/e/qux.py")), source_root),
    ) == Path("src/python/b/c")

    assert _call_find_common_dir(
        rule_runner,
        SourcePaths(
            (
                Path("src/python/b/c/bar.py"),
                Path("src/python/b/d/baz.py"),
                Path("src/python/b/c/e/qux.py"),
            ),
            source_root,
        ),
    ) == Path("src/python/b")

    assert _call_find_common_dir(
        rule_runner,
        SourcePaths(
            (
                Path("src/python/b/c/bar.py"),
                Path("src/python/b/d/baz.py"),
                Path("src/python/b/c/e/qux.py"),
                Path("src/python/b/c"),
            ),
            source_root,
        ),
    ) == Path("src/python/b")


def test_filter_by_suffixes_multiple_suffixes() -> None:
    source_root = SourceRoot("src/python")
    source_paths = SourcePaths(
        (
            Path("foo/bar.py"),
            Path("foo/baz.pyi"),
            Path("foo/qux.txt"),
            Path("foo/quux.py"),
        ),
        source_root,
    )

    filtered1 = source_paths.filter_by_suffixes((".py",))

    assert filtered1.paths == (
        Path("foo/bar.py"),
        Path("foo/quux.py"),
    )
    assert filtered1.source_root == source_root

    filtered2 = source_paths.filter_by_suffixes((".py", ".pyi"))

    assert filtered2.paths == (
        Path("foo/bar.py"),
        Path("foo/baz.pyi"),
        Path("foo/quux.py"),
    )
    assert filtered2.source_root == source_root

    filtered3 = source_paths.filter_by_suffixes((".txt",))
    assert filtered3.paths == (Path("foo/qux.txt"),)
    assert filtered3.source_root == source_root

    filtered4 = source_paths.filter_by_suffixes((".java",))
    assert filtered4.paths == ()
    assert filtered4.source_root == source_root


def test_partition_sources(tmp_path: Path) -> None:
    root1 = SourceRoot("src/py1")
    root2 = SourceRoot("src/py2")

    py1 = Path(root1.path)
    py2 = Path(root2.path)
    cfg_path = py1 / "foo" / "pantsng.toml"
    bar_path = py1 / "foo" / "bar.py"
    baz_path = py1 / "foo" / "baz.py"
    qux_path = py1 / "qux.py"
    corge_path = py2 / "corge.py"

    paths = Paths(
        files=(str(bar_path), str(baz_path), str(qux_path), str(corge_path)),
        dirs=(),
    )
    source_roots_result = SourceRootsResult(
        FrozenDict(
            {
                bar_path: root1,
                baz_path: root1,
                qux_path: root1,
                corge_path: root2,
            }
        )
    )

    with pushd(str(tmp_path)):
        (tmp_path / "BUILD_ROOT").touch()
        ng_options = PyNgOptions(PyNgInvocation.empty(), {}, include_derivation=False)
        cfg_path.parent.mkdir(parents=True)
        cfg_path.touch()

        partitions = run_rule_with_mocks(
            partition_sources,
            rule_args=[PathGlobs(["src/**/*.py"])],
            mock_calls={
                "pants.ng.source_partition.get_ng_options": lambda **kwargs: ng_options,
                "pants.engine.intrinsics.path_globs_to_paths": lambda _: paths,
                "pants.source.source_root.get_source_roots": lambda _: source_roots_result,
            },
        )

    assert len(partitions) == 3
    part1, part2, part3 = sorted(
        partitions, key=lambda part: (part.source_paths.source_root.path, part.source_paths.paths)
    )

    assert part1.source_paths.source_root == root1
    assert part1.source_paths.paths == (bar_path, baz_path)

    assert part2.source_paths.source_root == root1
    assert part2.source_paths.paths == (qux_path,)

    assert part3.source_paths.source_root == root2
    assert part3.source_paths.paths == (corge_path,)
