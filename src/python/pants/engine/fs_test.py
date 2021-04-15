# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import os
import pkgutil
import shutil
import ssl
import tarfile
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from io import BytesIO
from pathlib import Path
from typing import Callable, Iterable, Optional, Set

import pytest

from pants.engine.console import Console
from pants.engine.fs import (
    EMPTY_DIGEST,
    EMPTY_SNAPSHOT,
    AddPrefix,
    CreateDigest,
    Digest,
    DigestContents,
    DigestSubset,
    Directory,
    DownloadFile,
    FileContent,
    FileDigest,
    GlobMatchErrorBehavior,
    MergeDigests,
    PathGlobs,
    PathGlobsAndRoot,
    RemovePrefix,
    Snapshot,
    Workspace,
)
from pants.engine.goal import Goal, GoalSubsystem
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.rules import Get, goal_rule, rule
from pants.testutil.rule_runner import QueryRule, RuleRunner
from pants.util.collections import assert_single_element
from pants.util.contextutil import http_server, temporary_dir
from pants.util.dirutil import relative_symlink, safe_file_dump


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        rules=[
            QueryRule(DigestContents, [PathGlobs]),
            QueryRule(Snapshot, [CreateDigest]),
            QueryRule(Snapshot, [DigestSubset]),
            QueryRule(Snapshot, [PathGlobs]),
        ],
        isolated_local_store=True,
    )


ROLAND_DIGEST = Digest("63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16", 80)


def prime_store_with_roland_digest(rule_runner: RuleRunner) -> None:
    """Prime lmdb_store with a directory of a file named 'roland' and contents 'European
    Burmese'."""
    with temporary_dir() as temp_dir:
        Path(temp_dir, "roland").write_text("European Burmese")
        snapshot = rule_runner.scheduler.capture_snapshots(
            (PathGlobsAndRoot(PathGlobs(["*"]), temp_dir),)
        )[0]
    assert snapshot.files == ("roland",)
    assert snapshot.digest == ROLAND_DIGEST


def setup_fs_test_tar(rule_runner: RuleRunner) -> None:
    """Extract fs_test.tar into the rule_runner's build root.

    Note that we use a tar, rather than rule_runner.create_file(), because it has symlinks set up a
    certain way.

    Contents:

        4.txt
        a
        ├── 3.txt
        ├── 4.txt.ln -> ../4.txt
        └── b
            ├── 1.txt
            └── 2
        c.ln -> a/b
        d.ln -> a
    """
    data = pkgutil.get_data("pants.engine.internals", "fs_test_data/fs_test.tar")
    assert data is not None
    io = BytesIO()
    io.write(data)
    io.seek(0)
    with tarfile.open(fileobj=io) as tf:
        tf.extractall(rule_runner.build_root)


FS_TAR_ALL_FILES = (
    "4.txt",
    "a/3.txt",
    "a/4.txt.ln",
    "a/b/1.txt",
    "a/b/2",
    "c.ln/1.txt",
    "c.ln/2",
    "d.ln/3.txt",
    "d.ln/4.txt.ln",
    "d.ln/b/1.txt",
    "d.ln/b/2",
)
FS_TAR_ALL_DIRS = ("a", "a/b", "c.ln", "d.ln", "d.ln/b")


def try_with_backoff(assertion_fn: Callable[[], bool]) -> bool:
    for i in range(4):
        time.sleep(0.1 * i)
        if assertion_fn():
            return True
    return False


# -----------------------------------------------------------------------------------------------
# `PathGlobs`, including `GlobMatchErrorBehavior` and symlink handling
# -----------------------------------------------------------------------------------------------


def assert_path_globs(
    rule_runner: RuleRunner,
    globs: Iterable[str],
    *,
    expected_files: Iterable[str],
    expected_dirs: Iterable[str],
) -> None:
    snapshot = rule_runner.request(Snapshot, [PathGlobs(globs)])
    assert snapshot.files == tuple(sorted(expected_files))
    assert snapshot.dirs == tuple(sorted(expected_dirs))
    if expected_files or expected_dirs:
        assert snapshot.digest != EMPTY_DIGEST
    else:
        assert snapshot.digest == EMPTY_DIGEST


def test_path_globs_literal_files(rule_runner: RuleRunner) -> None:
    setup_fs_test_tar(rule_runner)
    assert_path_globs(rule_runner, ["4.txt"], expected_files=["4.txt"], expected_dirs=[])
    assert_path_globs(
        rule_runner,
        ["a/b/1.txt", "a/b/2"],
        expected_files=["a/b/1.txt", "a/b/2"],
        expected_dirs=["a", "a/b"],
    )
    assert_path_globs(rule_runner, ["c.ln/2"], expected_files=["c.ln/2"], expected_dirs=["c.ln"])
    assert_path_globs(
        rule_runner,
        ["d.ln/b/1.txt"],
        expected_files=["d.ln/b/1.txt"],
        expected_dirs=["d.ln", "d.ln/b"],
    )
    assert_path_globs(rule_runner, ["a/3.txt"], expected_files=["a/3.txt"], expected_dirs=["a"])
    assert_path_globs(rule_runner, ["z.fake"], expected_files=[], expected_dirs=[])


def test_path_globs_literal_directories(rule_runner: RuleRunner) -> None:
    setup_fs_test_tar(rule_runner)
    assert_path_globs(rule_runner, ["c.ln"], expected_files=[], expected_dirs=["c.ln"])
    assert_path_globs(rule_runner, ["a"], expected_files=[], expected_dirs=["a"])
    assert_path_globs(rule_runner, ["a/b"], expected_files=[], expected_dirs=["a", "a/b"])
    assert_path_globs(rule_runner, ["z"], expected_files=[], expected_dirs=[])


def test_path_globs_glob_pattern(rule_runner: RuleRunner) -> None:
    setup_fs_test_tar(rule_runner)
    assert_path_globs(rule_runner, ["*.txt"], expected_files=["4.txt"], expected_dirs=[])
    assert_path_globs(
        rule_runner, ["a/b/*.txt"], expected_files=["a/b/1.txt"], expected_dirs=["a", "a/b"]
    )
    assert_path_globs(
        rule_runner, ["c.ln/*.txt"], expected_files=["c.ln/1.txt"], expected_dirs=["c.ln"]
    )
    assert_path_globs(
        rule_runner, ["a/b/*"], expected_files=["a/b/1.txt", "a/b/2"], expected_dirs=["a", "a/b"]
    )
    assert_path_globs(rule_runner, ["*/0.txt"], expected_files=[], expected_dirs=[])
    assert_path_globs(
        rule_runner, ["*"], expected_files=["4.txt"], expected_dirs=["a", "c.ln", "d.ln"]
    )
    assert_path_globs(
        rule_runner,
        ["*/*"],
        expected_files=[
            "a/3.txt",
            "a/4.txt.ln",
            "c.ln/1.txt",
            "c.ln/2",
            "d.ln/3.txt",
            "d.ln/4.txt.ln",
        ],
        expected_dirs=FS_TAR_ALL_DIRS,
    )
    assert_path_globs(
        rule_runner,
        ["*/*/*"],
        expected_files=["a/b/1.txt", "a/b/2", "d.ln/b/1.txt", "d.ln/b/2"],
        expected_dirs=["a", "a/b", "d.ln", "d.ln/b"],
    )


def test_path_globs_rglob_pattern(rule_runner: RuleRunner) -> None:
    setup_fs_test_tar(rule_runner)
    assert_path_globs(
        rule_runner,
        ["**/*.txt.ln"],
        expected_files=["a/4.txt.ln", "d.ln/4.txt.ln"],
        expected_dirs=["a", "d.ln"],
    )
    assert_path_globs(
        rule_runner,
        ["**/*.txt"],
        expected_files=[
            "4.txt",
            "a/3.txt",
            "a/b/1.txt",
            "c.ln/1.txt",
            "d.ln/3.txt",
            "d.ln/b/1.txt",
        ],
        expected_dirs=FS_TAR_ALL_DIRS,
    )
    assert_path_globs(
        rule_runner,
        ["**/3.t*t"],
        expected_files=["a/3.txt", "d.ln/3.txt"],
        expected_dirs=["a", "d.ln"],
    )
    assert_path_globs(rule_runner, ["**/*.fake"], expected_files=[], expected_dirs=[])
    assert_path_globs(
        rule_runner, ["**"], expected_files=FS_TAR_ALL_FILES, expected_dirs=FS_TAR_ALL_DIRS
    )
    assert_path_globs(
        rule_runner, ["**/*"], expected_files=FS_TAR_ALL_FILES, expected_dirs=FS_TAR_ALL_DIRS
    )
    assert_path_globs(
        rule_runner,
        ["a/**"],
        expected_files=["a/3.txt", "a/4.txt.ln", "a/b/1.txt", "a/b/2"],
        expected_dirs=["a", "a/b"],
    )
    assert_path_globs(
        rule_runner,
        ["d.ln/**"],
        expected_files=["d.ln/3.txt", "d.ln/4.txt.ln", "d.ln/b/1.txt", "d.ln/b/2"],
        expected_dirs=["d.ln", "d.ln/b"],
    )
    assert_path_globs(rule_runner, ["a/**/3.txt"], expected_files=["a/3.txt"], expected_dirs=["a"])
    assert_path_globs(
        rule_runner, ["a/**/b/1.txt"], expected_files=["a/b/1.txt"], expected_dirs=["a", "a/b"]
    )
    assert_path_globs(rule_runner, ["a/**/2"], expected_files=["a/b/2"], expected_dirs=["a", "a/b"])


def test_path_globs_ignore_pattern(rule_runner: RuleRunner) -> None:
    setup_fs_test_tar(rule_runner)
    assert_path_globs(
        rule_runner,
        ["**", "!*.ln"],
        expected_files=["4.txt", "a/3.txt", "a/b/1.txt", "a/b/2"],
        expected_dirs=["a", "a/b"],
    )


def test_path_globs_remove_duplicates(rule_runner: RuleRunner) -> None:
    setup_fs_test_tar(rule_runner)
    assert_path_globs(
        rule_runner, ["*", "**"], expected_files=FS_TAR_ALL_FILES, expected_dirs=FS_TAR_ALL_DIRS
    )
    assert_path_globs(
        rule_runner,
        ["**/*.txt", "a/b/1.txt", "4.txt"],
        expected_files=[
            "4.txt",
            "a/3.txt",
            "c.ln/1.txt",
            "d.ln/3.txt",
            "a/b/1.txt",
            "d.ln/b/1.txt",
        ],
        expected_dirs=FS_TAR_ALL_DIRS,
    )


def test_path_globs_parent_link(rule_runner: RuleRunner) -> None:
    setup_fs_test_tar(rule_runner)
    assert_path_globs(
        rule_runner,
        ["c.ln/../3.txt"],
        expected_files=["c.ln/../3.txt"],
        expected_dirs=["c.ln", "c.ln/.."],
    )


def test_path_globs_symlink_escaping_errors(rule_runner: RuleRunner) -> None:
    setup_fs_test_tar(rule_runner)
    link = os.path.join(rule_runner.build_root, "subdir/escaping")
    dest = os.path.join(rule_runner.build_root, "../../..")
    relative_symlink(dest, link)

    exc_reg = r".*While expanding link.*subdir/escaping.*may not traverse outside of the buildroot"
    with pytest.raises(Exception, match=exc_reg):
        assert_path_globs(rule_runner, ["subdir/escaping"], expected_files=[], expected_dirs=[])


def test_path_globs_symlink_dead(rule_runner: RuleRunner) -> None:
    setup_fs_test_tar(rule_runner)
    link = os.path.join(rule_runner.build_root, "subdir/dead")
    dest = os.path.join(rule_runner.build_root, "this_file_does_not_exist")
    relative_symlink(dest, link)

    # Because the symlink does not escape, it should be ignored, rather than cause an error.
    assert_path_globs(rule_runner, ["subdir/dead"], expected_files=[], expected_dirs=[])


def test_path_globs_symlink_dead_nested(rule_runner: RuleRunner) -> None:
    setup_fs_test_tar(rule_runner)
    link = os.path.join(rule_runner.build_root, "subdir/dead")
    dest = os.path.join(
        rule_runner.build_root, "this_folder_does_not_exist/this_file_does_not_exist"
    )
    relative_symlink(dest, link)

    # Because the symlink does not escape, it should be ignored, rather than cause an error.
    assert_path_globs(rule_runner, ["subdir/dead"], expected_files=[], expected_dirs=[])


def test_path_globs_to_digest_contents(rule_runner: RuleRunner) -> None:
    setup_fs_test_tar(rule_runner)

    def get_contents(globs: Iterable[str]) -> Set[FileContent]:
        return set(rule_runner.request(DigestContents, [PathGlobs(globs)]))

    assert get_contents(["4.txt", "a/4.txt.ln"]) == {
        FileContent("4.txt", b"four\n"),
        FileContent("a/4.txt.ln", b"four\n"),
    }
    assert get_contents(["c.ln/../3.txt"]) == {FileContent("c.ln/../3.txt", b"three\n")}

    # Directories are empty.
    assert not get_contents(["a/b"])
    assert not get_contents(["c.ln"])


def test_glob_match_error_behavior(rule_runner: RuleRunner, caplog) -> None:
    setup_fs_test_tar(rule_runner)
    test_name = f"{__name__}.{test_glob_match_error_behavior.__name__}()"

    def evaluate_path_globs(globs: Iterable[str], error_behavior: GlobMatchErrorBehavior) -> None:
        pg = PathGlobs(
            globs,
            glob_match_error_behavior=error_behavior,
            description_of_origin=(
                test_name if error_behavior != GlobMatchErrorBehavior.ignore else None
            ),
        )
        rule_runner.request(Snapshot, [pg])

    with pytest.raises(Exception) as exc:
        evaluate_path_globs(["not-a-file.txt"], GlobMatchErrorBehavior.error)
    assert f'Unmatched glob from {test_name}: "not-a-file.txt"' in str(exc.value)

    with pytest.raises(Exception) as exc:
        evaluate_path_globs(["not-a-file.txt", "!ignore.txt"], GlobMatchErrorBehavior.error)
    assert f'Unmatched glob from {test_name}: "not-a-file.txt", exclude: "ignore.txt"' in str(
        exc.value
    )

    # TODO: get Rust logging working with RuleRunner.
    # caplog.clear()
    # evaluate_path_globs(["not-a-file.txt"], GlobMatchErrorBehavior.warn)
    # assert len(caplog.records) == 1
    # assert f'Unmatched glob from {test_name}: "not-a-file.txt"' in caplog.text

    caplog.clear()
    evaluate_path_globs(["not-a-file.txt"], GlobMatchErrorBehavior.ignore)
    assert len(caplog.records) == 0


# -----------------------------------------------------------------------------------------------
# `PathGlobsAndRoot`
# -----------------------------------------------------------------------------------------------


def test_snapshot_from_outside_buildroot(rule_runner: RuleRunner) -> None:
    with temporary_dir() as temp_dir:
        Path(temp_dir, "roland").write_text("European Burmese")
        snapshot = rule_runner.scheduler.capture_snapshots(
            [PathGlobsAndRoot(PathGlobs(["*"]), temp_dir)]
        )[0]
    assert snapshot.files == ("roland",)
    assert snapshot.digest == ROLAND_DIGEST


def test_multiple_snapshots_from_outside_buildroot(rule_runner: RuleRunner) -> None:
    with temporary_dir() as temp_dir:
        Path(temp_dir, "roland").write_text("European Burmese")
        Path(temp_dir, "susannah").write_text("I don't know")
        snapshots = rule_runner.scheduler.capture_snapshots(
            [
                PathGlobsAndRoot(PathGlobs(["roland"]), temp_dir),
                PathGlobsAndRoot(PathGlobs(["susannah"]), temp_dir),
                PathGlobsAndRoot(PathGlobs(["doesnotexist"]), temp_dir),
            ]
        )
    assert len(snapshots) == 3
    assert snapshots[0].files == ("roland",)
    assert snapshots[0].digest == ROLAND_DIGEST
    assert snapshots[1].files == ("susannah",)
    assert snapshots[1].digest == Digest(
        "d3539cfc21eb4bab328ca9173144a8e932c515b1b9e26695454eeedbc5a95f6f", 82
    )
    assert snapshots[2] == EMPTY_SNAPSHOT


def test_snapshot_from_outside_buildroot_failure(rule_runner: RuleRunner) -> None:
    with temporary_dir() as temp_dir:
        with pytest.raises(Exception) as exc:
            rule_runner.scheduler.capture_snapshots(
                [PathGlobsAndRoot(PathGlobs(["*"]), os.path.join(temp_dir, "doesnotexist"))]
            )
    assert "doesnotexist" in str(exc.value)


# -----------------------------------------------------------------------------------------------
# `CreateDigest`
# -----------------------------------------------------------------------------------------------


def test_create_empty_directory(rule_runner: RuleRunner) -> None:
    res = rule_runner.request(Snapshot, [CreateDigest([Directory("a/")])])
    assert res.dirs == ("a",)
    assert not res.files
    assert res.digest != EMPTY_DIGEST

    res = rule_runner.request(
        Snapshot, [CreateDigest([Directory("x/y/z"), Directory("m"), Directory("m/n")])]
    )
    assert res.dirs == ("m", "m/n", "x", "x/y", "x/y/z")
    assert not res.files
    assert res.digest != EMPTY_DIGEST


# -----------------------------------------------------------------------------------------------
# `MergeDigests`
# -----------------------------------------------------------------------------------------------


def test_merge_digests(rule_runner: RuleRunner) -> None:
    with temporary_dir() as temp_dir:
        Path(temp_dir, "roland").write_text("European Burmese")
        Path(temp_dir, "susannah").write_text("Not sure actually")
        (
            empty_snapshot,
            roland_snapshot,
            susannah_snapshot,
            both_snapshot,
        ) = rule_runner.scheduler.capture_snapshots(
            (
                PathGlobsAndRoot(PathGlobs(["doesnotmatch"]), temp_dir),
                PathGlobsAndRoot(PathGlobs(["roland"]), temp_dir),
                PathGlobsAndRoot(PathGlobs(["susannah"]), temp_dir),
                PathGlobsAndRoot(PathGlobs(["*"]), temp_dir),
            )
        )

    empty_merged = rule_runner.request(Digest, [MergeDigests((empty_snapshot.digest,))])
    assert empty_snapshot.digest == empty_merged

    roland_merged = rule_runner.request(
        Digest, [MergeDigests((roland_snapshot.digest, empty_snapshot.digest))]
    )
    assert roland_snapshot.digest == roland_merged

    both_merged = rule_runner.request(
        Digest, [MergeDigests((roland_snapshot.digest, susannah_snapshot.digest))]
    )
    assert both_snapshot.digest == both_merged


# -----------------------------------------------------------------------------------------------
# `DigestSubset`
# -----------------------------------------------------------------------------------------------


def generate_original_digest(rule_runner: RuleRunner) -> Digest:
    files = [
        FileContent(path, b"dummy content")
        for path in [
            "a.txt",
            "b.txt",
            "c.txt",
            "subdir/a.txt",
            "subdir/b.txt",
            "subdir2/a.txt",
            "subdir2/nested_subdir/x.txt",
        ]
    ]
    return rule_runner.request(
        Digest,
        [CreateDigest(files)],
    )


def test_digest_subset_empty(rule_runner: RuleRunner) -> None:
    subset_snapshot = rule_runner.request(
        Snapshot, [DigestSubset(generate_original_digest(rule_runner), PathGlobs(()))]
    )
    assert subset_snapshot.digest == EMPTY_DIGEST
    assert subset_snapshot.files == ()
    assert subset_snapshot.dirs == ()


def test_digest_subset_globs(rule_runner: RuleRunner) -> None:
    subset_snapshot = rule_runner.request(
        Snapshot,
        [
            DigestSubset(
                generate_original_digest(rule_runner),
                PathGlobs(("a.txt", "c.txt", "subdir2/**")),
            )
        ],
    )
    assert set(subset_snapshot.files) == {
        "a.txt",
        "c.txt",
        "subdir2/a.txt",
        "subdir2/nested_subdir/x.txt",
    }
    assert set(subset_snapshot.dirs) == {"subdir2", "subdir2/nested_subdir"}

    expected_files = [
        FileContent(path, b"dummy content")
        for path in [
            "a.txt",
            "c.txt",
            "subdir2/a.txt",
            "subdir2/nested_subdir/x.txt",
        ]
    ]
    subset_digest = rule_runner.request(Digest, [CreateDigest(expected_files)])
    assert subset_snapshot.digest == subset_digest


def test_digest_subset_globs_2(rule_runner: RuleRunner) -> None:
    subset_snapshot = rule_runner.request(
        Snapshot,
        [
            DigestSubset(
                generate_original_digest(rule_runner), PathGlobs(("a.txt", "c.txt", "subdir2/*"))
            )
        ],
    )
    assert set(subset_snapshot.files) == {"a.txt", "c.txt", "subdir2/a.txt"}
    assert set(subset_snapshot.dirs) == {"subdir2", "subdir2/nested_subdir"}


def test_digest_subset_nonexistent_filename_globs(rule_runner: RuleRunner) -> None:
    # We behave according to the `GlobMatchErrorBehavior`.
    original_digest = generate_original_digest(rule_runner)
    globs = ["some_file_not_in_snapshot.txt", "a.txt"]
    subset_snapshot = rule_runner.request(
        Snapshot, [DigestSubset(original_digest, PathGlobs(globs))]
    )
    assert set(subset_snapshot.files) == {"a.txt"}
    expected_digest = rule_runner.request(
        Digest, [CreateDigest([FileContent("a.txt", b"dummy content")])]
    )
    assert subset_snapshot.digest == expected_digest

    # TODO: Fix this to actually error.
    # with pytest.raises(ExecutionError):
    #     rule_runner.request(
    #         Snapshot,
    #         [
    #             DigestSubset(
    #                 original_digest,
    #                 PathGlobs(
    #                     globs,
    #                     glob_match_error_behavior=GlobMatchErrorBehavior.error,
    #                     conjunction=GlobExpansionConjunction.all_match,
    #                     description_of_origin="test",
    #                 ),
    #             )
    #         ],
    #     )


# -----------------------------------------------------------------------------------------------
# `Digest` -> `Snapshot`
# -----------------------------------------------------------------------------------------------


def test_lift_digest_to_snapshot(rule_runner: RuleRunner) -> None:
    prime_store_with_roland_digest(rule_runner)
    snapshot = rule_runner.request(Snapshot, [ROLAND_DIGEST])
    assert snapshot.files == ("roland",)
    assert snapshot.digest == ROLAND_DIGEST


def test_error_lifting_file_digest_to_snapshot(rule_runner: RuleRunner) -> None:
    prime_store_with_roland_digest(rule_runner)
    # A file digest is not a directory digest. Here, we hash the file that was primed as part of
    # that directory, and show that we can't turn it into a Snapshot.
    text = b"European Burmese"
    hasher = hashlib.sha256()
    hasher.update(text)
    digest = Digest(fingerprint=hasher.hexdigest(), serialized_bytes_length=len(text))
    with pytest.raises(ExecutionError) as exc:
        rule_runner.request(Snapshot, [digest])
    assert "unknown directory" in str(exc.value)


# -----------------------------------------------------------------------------------------------
# `AddPrefix` and `RemovePrefix`
# -----------------------------------------------------------------------------------------------


def test_add_prefix(rule_runner: RuleRunner) -> None:
    digest = rule_runner.request(
        Digest,
        [CreateDigest([FileContent("main.ext", b""), FileContent("subdir/sub.ext", b"")])],
    )

    # Two components.
    output_digest = rule_runner.request(Digest, [AddPrefix(digest, "outer_dir/middle_dir")])
    snapshot = rule_runner.request(Snapshot, [output_digest])
    assert sorted(snapshot.files) == [
        "outer_dir/middle_dir/main.ext",
        "outer_dir/middle_dir/subdir/sub.ext",
    ]
    assert sorted(snapshot.dirs) == [
        "outer_dir",
        "outer_dir/middle_dir",
        "outer_dir/middle_dir/subdir",
    ]

    # Empty.
    output_digest = rule_runner.request(Digest, [AddPrefix(digest, "")])
    assert digest == output_digest

    # Illegal.
    with pytest.raises(Exception, match=r"The `prefix` must be relative."):
        rule_runner.request(Digest, [AddPrefix(digest, "../something")])


def test_remove_prefix(rule_runner: RuleRunner) -> None:
    relevant_files = (
        "characters/dark_tower/roland",
        "characters/dark_tower/susannah",
    )
    all_files = (
        "books/dark_tower/gunslinger",
        "characters/altered_carbon/kovacs",
        *relevant_files,
        "index",
    )

    with temporary_dir() as temp_dir:
        safe_file_dump(os.path.join(temp_dir, "index"), "books\ncharacters\n")
        safe_file_dump(
            os.path.join(temp_dir, "characters", "altered_carbon", "kovacs"),
            "Envoy",
            makedirs=True,
        )

        tower_dir = os.path.join(temp_dir, "characters", "dark_tower")
        safe_file_dump(os.path.join(tower_dir, "roland"), "European Burmese", makedirs=True)
        safe_file_dump(os.path.join(tower_dir, "susannah"), "Not sure actually", makedirs=True)

        safe_file_dump(
            os.path.join(temp_dir, "books", "dark_tower", "gunslinger"),
            "1982",
            makedirs=True,
        )

        snapshot, snapshot_with_extra_files = rule_runner.scheduler.capture_snapshots(
            [
                PathGlobsAndRoot(PathGlobs(["characters/dark_tower/*"]), temp_dir),
                PathGlobsAndRoot(PathGlobs(["**"]), temp_dir),
            ]
        )

        # Check that we got the full snapshots that we expect
        assert snapshot.files == relevant_files
        assert snapshot_with_extra_files.files == all_files

        # Strip empty prefix:
        zero_prefix_stripped_digest = rule_runner.request(
            Digest, [RemovePrefix(snapshot.digest, "")]
        )
        assert snapshot.digest == zero_prefix_stripped_digest

        # Strip a non-empty prefix shared by all files:
        stripped_digest = rule_runner.request(
            Digest, [RemovePrefix(snapshot.digest, "characters/dark_tower")]
        )
        assert stripped_digest == Digest(
            fingerprint="71e788fc25783c424db555477071f5e476d942fc958a5d06ffc1ed223f779a8c",
            serialized_bytes_length=162,
        )

        expected_snapshot = assert_single_element(
            rule_runner.scheduler.capture_snapshots([PathGlobsAndRoot(PathGlobs(["*"]), tower_dir)])
        )
        assert expected_snapshot.files == ("roland", "susannah")
        assert stripped_digest == expected_snapshot.digest

        # Try to strip a prefix which isn't shared by all files:
        with pytest.raises(Exception) as exc:
            rule_runner.request(
                Digest,
                [RemovePrefix(snapshot_with_extra_files.digest, "characters/dark_tower")],
            )
        assert (
            "Cannot strip prefix characters/dark_tower from root directory (Digest "
            "with hash Fingerprint<28c47f77867f0c8d577d2ada2f06b03fc8e5ef2d780e8942713b26c5e3f434b8>)"
            " - root directory contained non-matching directory named: books and file named: index"
        ) in str(exc.value)


# -----------------------------------------------------------------------------------------------
# `DownloadFile`
# -----------------------------------------------------------------------------------------------


@pytest.fixture
def downloads_rule_runner() -> RuleRunner:
    return RuleRunner(rules=[QueryRule(Snapshot, [DownloadFile])], isolated_local_store=True)


class StubHandler(BaseHTTPRequestHandler):
    response_text = b"Hello, client!"

    def do_HEAD(self):
        self.send_headers()

    def do_GET(self):
        self.send_headers()
        self.wfile.write(self.response_text)

    def send_headers(self):
        code = 200 if self.path == "/file.txt" else 404
        self.send_response(code)
        self.send_header("Content-Type", "text/utf-8")
        self.send_header("Content-Length", f"{len(self.response_text)}")
        self.end_headers()


DOWNLOADS_FILE_DIGEST = FileDigest(
    "8fcbc50cda241aee7238c71e87c27804e7abc60675974eaf6567aa16366bc105", 14
)
DOWNLOADS_EXPECTED_DIRECTORY_DIGEST = Digest(
    "4c9cf91fcd7ba1abbf7f9a0a1c8175556a82bee6a398e34db3284525ac24a3ad", 84
)


def test_download_valid(downloads_rule_runner: RuleRunner) -> None:
    with http_server(StubHandler) as port:
        snapshot = downloads_rule_runner.request(
            Snapshot, [DownloadFile(f"http://localhost:{port}/file.txt", DOWNLOADS_FILE_DIGEST)]
        )
    assert snapshot.files == ("file.txt",)
    assert snapshot.digest == DOWNLOADS_EXPECTED_DIRECTORY_DIGEST


def test_download_missing_file(downloads_rule_runner: RuleRunner) -> None:
    with pytest.raises(ExecutionError) as exc:
        with http_server(StubHandler) as port:
            downloads_rule_runner.request(
                Snapshot, [DownloadFile(f"http://localhost:{port}/notfound", DOWNLOADS_FILE_DIGEST)]
            )
    assert "404" in str(exc.value)


def test_download_wrong_digest(downloads_rule_runner: RuleRunner) -> None:
    file_digest = FileDigest(
        DOWNLOADS_FILE_DIGEST.fingerprint, DOWNLOADS_FILE_DIGEST.serialized_bytes_length + 1
    )
    with pytest.raises(ExecutionError) as exc:
        with http_server(StubHandler) as port:
            downloads_rule_runner.request(
                Snapshot, [DownloadFile(f"http://localhost:{port}/file.txt", file_digest)]
            )
    assert "wrong digest" in str(exc.value).lower()


def test_download_caches(downloads_rule_runner: RuleRunner) -> None:
    # We would error if we hit the HTTP server with 404, but we're not going to hit the HTTP
    # server because it's cached, so we shouldn't see an error.
    prime_store_with_roland_digest(downloads_rule_runner)
    with http_server(StubHandler) as port:
        download_file = DownloadFile(
            f"http://localhost:{port}/roland",
            FileDigest("693d8db7b05e99c6b7a7c0616456039d89c555029026936248085193559a0b5d", 16),
        )
        snapshot = downloads_rule_runner.request(Snapshot, [download_file])
    assert snapshot.files == ("roland",)
    assert snapshot.digest == Digest(
        "9341f76bef74170bedffe51e4f2e233f61786b7752d21c2339f8ee6070eba819", 82
    )


def test_download_https() -> None:
    # This also tests that the custom certs functionality works.
    with temporary_dir() as temp_dir:

        def write_resource(name: str) -> Path:
            path = Path(temp_dir) / name
            data = pkgutil.get_data("pants.engine.internals", f"fs_test_data/tls/rsa/{name}")
            assert data is not None
            path.write_bytes(data)
            return path

        server_cert = write_resource("server.crt")
        server_key = write_resource("server.key")
        cert_chain = write_resource("server.chain")

        rule_runner = RuleRunner(
            rules=[QueryRule(Snapshot, [DownloadFile])],
            isolated_local_store=True,
            ca_certs_path=str(cert_chain),
        )

        ssl_context = ssl.SSLContext()
        ssl_context.load_cert_chain(certfile=str(server_cert), keyfile=str(server_key))

        with http_server(StubHandler, ssl_context=ssl_context) as port:
            snapshot = rule_runner.request(
                Snapshot,
                [DownloadFile(f"https://localhost:{port}/file.txt", DOWNLOADS_FILE_DIGEST)],
            )

    assert snapshot.files == ("file.txt",)
    assert snapshot.digest == DOWNLOADS_EXPECTED_DIRECTORY_DIGEST


# -----------------------------------------------------------------------------------------------
# `Workspace` and `.write_digest()`
# -----------------------------------------------------------------------------------------------


def test_write_digest_scheduler(rule_runner: RuleRunner) -> None:
    prime_store_with_roland_digest(rule_runner)

    path = Path(rule_runner.build_root, "roland")
    assert not path.is_file()

    rule_runner.scheduler.write_digest(ROLAND_DIGEST)
    assert path.is_file()
    assert path.read_text() == "European Burmese"

    rule_runner.scheduler.write_digest(ROLAND_DIGEST, path_prefix="test/")
    path = Path(rule_runner.build_root, "test/roland")
    assert path.is_file()
    assert path.read_text() == "European Burmese"


def test_write_digest_workspace(rule_runner: RuleRunner) -> None:
    workspace = Workspace(rule_runner.scheduler)
    digest = rule_runner.request(
        Digest,
        [CreateDigest([FileContent("a.txt", b"hello"), FileContent("subdir/b.txt", b"goodbye")])],
    )

    path1 = Path(rule_runner.build_root, "a.txt")
    path2 = Path(rule_runner.build_root, "subdir/b.txt")
    assert not path1.is_file()
    assert not path2.is_file()

    workspace.write_digest(digest)
    assert path1.is_file()
    assert path2.is_file()
    assert path1.read_text() == "hello"
    assert path2.read_text() == "goodbye"

    workspace.write_digest(digest, path_prefix="prefix")
    path1 = Path(rule_runner.build_root, "prefix/a.txt")
    path2 = Path(rule_runner.build_root, "prefix/subdir/b.txt")
    assert path1.is_file()
    assert path2.is_file()
    assert path1.read_text() == "hello"
    assert path2.read_text() == "goodbye"


def test_workspace_in_goal_rule() -> None:
    class WorkspaceGoalSubsystem(GoalSubsystem):
        name = "workspace-goal"

    class WorkspaceGoal(Goal):
        subsystem_cls = WorkspaceGoalSubsystem

    @dataclass(frozen=True)
    class DigestRequest:
        create_digest: CreateDigest

    @rule
    def digest_request_singleton() -> DigestRequest:
        fc = FileContent(path="a.txt", content=b"hello")
        return DigestRequest(CreateDigest([fc]))

    @goal_rule
    async def workspace_goal_rule(
        console: Console, workspace: Workspace, digest_request: DigestRequest
    ) -> WorkspaceGoal:
        snapshot = await Get(Snapshot, CreateDigest, digest_request.create_digest)
        workspace.write_digest(snapshot.digest)
        console.print_stdout(snapshot.files[0], end="")
        return WorkspaceGoal(exit_code=0)

    rule_runner = RuleRunner(rules=[workspace_goal_rule, digest_request_singleton])
    result = rule_runner.run_goal_rule(WorkspaceGoal)
    assert result.exit_code == 0
    assert result.stdout == "a.txt"
    assert Path(rule_runner.build_root, "a.txt").read_text() == "hello"


# -----------------------------------------------------------------------------------------------
# Invalidation of the FS
# -----------------------------------------------------------------------------------------------


def test_invalidated_after_rewrite(rule_runner: RuleRunner) -> None:
    """Test that updating files causes invalidation of previous operations on those files."""
    setup_fs_test_tar(rule_runner)

    def read_file() -> str:
        digest_contents = rule_runner.request(DigestContents, [PathGlobs(["4.txt"])])
        assert len(digest_contents) == 1
        return digest_contents[0].content.decode()

    # First read the file, which should cache it.
    assert read_file() == "four\n"

    new_value = "cuatro\n"
    Path(rule_runner.build_root, "4.txt").write_text(new_value)
    assert try_with_backoff(lambda: read_file() == new_value)


def test_invalidated_after_parent_deletion(rule_runner: RuleRunner) -> None:
    """Test that FileContent is invalidated after deleting parent directory."""
    setup_fs_test_tar(rule_runner)

    def read_file() -> Optional[str]:
        digest_contents = rule_runner.request(DigestContents, [PathGlobs(["a/b/1.txt"])])
        if not digest_contents:
            return None
        assert len(digest_contents) == 1
        return digest_contents[0].content.decode()

    # Read the original file so that we have nodes to invalidate.
    assert read_file() == "one\n"

    shutil.rmtree(Path(rule_runner.build_root, "a/b"))
    assert try_with_backoff(lambda: read_file() is None)


def test_invalidated_after_child_deletion(rule_runner: RuleRunner) -> None:
    setup_fs_test_tar(rule_runner)
    original_snapshot = rule_runner.request(Snapshot, [PathGlobs(["a/*"])])
    assert original_snapshot.files == ("a/3.txt", "a/4.txt.ln")
    assert original_snapshot.dirs == ("a", "a/b")

    Path(rule_runner.build_root, "a/3.txt").unlink()

    def is_changed_snapshot() -> bool:
        new_snapshot = rule_runner.request(Snapshot, [PathGlobs(["a/*"])])
        return (
            new_snapshot.digest != original_snapshot.digest
            and new_snapshot.files == ("a/4.txt.ln",)
            and new_snapshot.dirs == ("a", "a/b")
        )

    assert try_with_backoff(is_changed_snapshot)


def test_invalidated_after_new_child(rule_runner: RuleRunner) -> None:
    setup_fs_test_tar(rule_runner)
    original_snapshot = rule_runner.request(Snapshot, [PathGlobs(["a/*"])])
    assert original_snapshot.files == ("a/3.txt", "a/4.txt.ln")
    assert original_snapshot.dirs == ("a", "a/b")

    Path(rule_runner.build_root, "a/new_file.txt").write_text("new file")

    def is_changed_snapshot() -> bool:
        new_snapshot = rule_runner.request(Snapshot, [PathGlobs(["a/*"])])
        return (
            new_snapshot.digest != original_snapshot.digest
            and new_snapshot.files == ("a/3.txt", "a/4.txt.ln", "a/new_file.txt")
            and new_snapshot.dirs == ("a", "a/b")
        )

    assert try_with_backoff(is_changed_snapshot)


# -----------------------------------------------------------------------------------------------
# Comparison and representation of Digests
# -----------------------------------------------------------------------------------------------


def test_digest_repr() -> None:
    assert (
        str(Digest("f" * 64, 1))
        == "Digest('ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff', 1)"
    )


def test_digest_equality() -> None:
    assert Digest("f" * 64, 1) == Digest("f" * 64, 1)
    assert Digest("f" * 64, 1) != Digest("f" * 64, 1000)
    assert Digest("f" * 64, 1) != Digest("0" * 64, 1)
