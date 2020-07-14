# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import hashlib
import logging
import os
import shutil
import tarfile
import time
import unittest
from abc import ABCMeta
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Callable, List

from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.engine.fs import (
    EMPTY_DIGEST,
    AddPrefix,
    Digest,
    DirectoryToMaterialize,
    FileContent,
    FilesContent,
    InputFilesContent,
    MergeDigests,
    PathGlobs,
    PathGlobsAndRoot,
    RemovePrefix,
    Snapshot,
    SnapshotSubset,
    UrlToFetch,
    create_fs_rules,
)
from pants.engine.internals.scheduler import ExecutionError
from pants.engine.internals.scheduler_test_base import SchedulerTestBase
from pants.option.global_options import GlobMatchErrorBehavior
from pants.testutil.test_base import TestBase
from pants.util.collections import assert_single_element
from pants.util.contextutil import http_server, temporary_dir
from pants.util.dirutil import relative_symlink, safe_file_dump


class FSTest(TestBase, SchedulerTestBase, metaclass=ABCMeta):

    _original_src = os.path.join(
        os.path.dirname(__file__), "internals/examples/fs_test/fs_test.tar"
    )

    @contextmanager
    def mk_project_tree(self, ignore_patterns=None):
        """Construct a ProjectTree for the given src path."""
        project_tree = self.mk_fs_tree(ignore_patterns=ignore_patterns)
        with tarfile.open(self._original_src) as tar:
            tar.extractall(project_tree.build_root)
        yield project_tree

    @staticmethod
    def path_globs(globs) -> PathGlobs:
        if isinstance(globs, PathGlobs):
            return globs
        return PathGlobs(globs)

    def read_file_content(self, scheduler, filespecs_or_globs):
        """Helper method for reading the content of some files from an existing scheduler
        session."""
        snapshot = self.execute_expecting_one_result(
            scheduler, Snapshot, self.path_globs(filespecs_or_globs)
        ).value
        result = self.execute_expecting_one_result(scheduler, FilesContent, snapshot.digest).value
        return {f.path: f.content for f in result}

    def assert_walk_dirs(self, filespecs_or_globs, paths, **kwargs):
        self.assert_walk_snapshot("dirs", filespecs_or_globs, paths, **kwargs)

    def assert_walk_files(self, filespecs_or_globs, paths, **kwargs):
        self.assert_walk_snapshot("files", filespecs_or_globs, paths, **kwargs)

    def assert_walk_snapshot(
        self, field, filespecs_or_globs, paths, ignore_patterns=None, prepare=None
    ):
        with self.mk_project_tree(ignore_patterns=ignore_patterns) as project_tree:
            scheduler = self.mk_scheduler(rules=create_fs_rules(), project_tree=project_tree)
            if prepare:
                prepare(project_tree)
            result = self.execute(scheduler, Snapshot, self.path_globs(filespecs_or_globs))[0]
            assert sorted(getattr(result, field)) == sorted(paths)

    def assert_content(self, filespecs_or_globs, expected_content):
        with self.mk_project_tree() as project_tree:
            scheduler = self.mk_scheduler(rules=create_fs_rules(), project_tree=project_tree)
            actual_content = self.read_file_content(scheduler, filespecs_or_globs)
            assert expected_content == actual_content

    def assert_digest(self, filespecs_or_globs, expected_files):
        with self.mk_project_tree() as project_tree:
            scheduler = self.mk_scheduler(rules=create_fs_rules(), project_tree=project_tree)
            result = self.execute(scheduler, Snapshot, self.path_globs(filespecs_or_globs))[0]
            # Confirm all expected files were digested.
            assert set(expected_files) == set(result.files)
            assert result.digest.fingerprint is not None

    def test_walk_literal(self) -> None:
        self.assert_walk_files(["4.txt"], ["4.txt"])
        self.assert_walk_files(["a/b/1.txt", "a/b/2"], ["a/b/1.txt", "a/b/2"])
        self.assert_walk_files(["c.ln/2"], ["c.ln/2"])
        self.assert_walk_files(["d.ln/b/1.txt"], ["d.ln/b/1.txt"])
        self.assert_walk_files(["a/3.txt"], ["a/3.txt"])
        self.assert_walk_files(["z.txt"], [])

    def test_walk_literal_directory(self) -> None:
        self.assert_walk_dirs(["c.ln"], ["c.ln"])
        self.assert_walk_dirs(["a"], ["a"])
        self.assert_walk_dirs(["a/b"], ["a/b"])
        self.assert_walk_dirs(["z"], [])
        self.assert_walk_dirs(["4.txt", "a/3.txt"], [])

    def test_walk_siblings(self) -> None:
        self.assert_walk_files(["*.txt"], ["4.txt"])
        self.assert_walk_files(["a/b/*.txt"], ["a/b/1.txt"])
        self.assert_walk_files(["c.ln/*.txt"], ["c.ln/1.txt"])
        self.assert_walk_files(["a/b/*"], ["a/b/1.txt", "a/b/2"])
        self.assert_walk_files(["*/0.txt"], [])

    def test_walk_recursive(self) -> None:
        self.assert_walk_files(["**/*.txt.ln"], ["a/4.txt.ln", "d.ln/4.txt.ln"])
        self.assert_walk_files(
            ["**/*.txt"],
            ["4.txt", "a/3.txt", "a/b/1.txt", "c.ln/1.txt", "d.ln/3.txt", "d.ln/b/1.txt"],
        )
        self.assert_walk_files(
            ["**/*.txt"],
            ["a/3.txt", "a/b/1.txt", "c.ln/1.txt", "d.ln/3.txt", "d.ln/b/1.txt", "4.txt"],
        )
        self.assert_walk_files(["**/3.t*t"], ["a/3.txt", "d.ln/3.txt"])
        self.assert_walk_files(["**/*.zzz"], [])

    def test_walk_single_star(self) -> None:
        self.assert_walk_files(["*"], ["4.txt"])

    def test_walk_parent_link(self) -> None:
        self.assert_walk_files(["c.ln/../3.txt"], ["c.ln/../3.txt"])

    def test_walk_escaping_symlink(self) -> None:
        link = "subdir/escaping"
        dest = "../../"

        def prepare(project_tree):
            link_path = os.path.join(project_tree.build_root, link)
            dest_path = os.path.join(project_tree.build_root, dest)
            relative_symlink(dest_path, link_path)

        exc_reg = (
            f".*While expanding link.*{link}.*may not traverse outside of the buildroot.*{dest}.*"
        )
        with self.assertRaisesRegex(Exception, exc_reg):
            self.assert_walk_files([link], [], prepare=prepare)

    def test_walk_recursive_all(self) -> None:
        self.assert_walk_files(
            ["**"],
            [
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
            ],
        )

    def test_walk_ignore(self) -> None:
        # Ignore '*.ln' suffixed items at the root.
        self.assert_walk_files(
            ["**"],
            ["4.txt", "a/3.txt", "a/4.txt.ln", "a/b/1.txt", "a/b/2"],
            ignore_patterns=["/*.ln"],
        )
        # Whitelist one entry.
        self.assert_walk_files(
            ["**"],
            ["4.txt", "a/3.txt", "a/4.txt.ln", "a/b/1.txt", "a/b/2", "c.ln/1.txt", "c.ln/2"],
            ignore_patterns=["/*.ln", "!c.ln"],
        )

    def test_walk_recursive_trailing_doublestar(self) -> None:
        self.assert_walk_files(["a/**"], ["a/3.txt", "a/4.txt.ln", "a/b/1.txt", "a/b/2"])
        self.assert_walk_files(
            ["d.ln/**"], ["d.ln/3.txt", "d.ln/4.txt.ln", "d.ln/b/1.txt", "d.ln/b/2"]
        )
        self.assert_walk_dirs(["a/**"], ["a/b"])

    def test_walk_recursive_slash_doublestar_slash(self) -> None:
        self.assert_walk_files(["a/**/3.txt"], ["a/3.txt"])
        self.assert_walk_files(["a/**/b/1.txt"], ["a/b/1.txt"])
        self.assert_walk_files(["a/**/2"], ["a/b/2"])

    def test_walk_recursive_directory(self) -> None:
        self.assert_walk_dirs(["*"], ["a", "c.ln", "d.ln"])
        self.assert_walk_dirs(["*/*"], ["a/b", "d.ln/b"])
        self.assert_walk_dirs(["**/*"], ["a", "c.ln", "d.ln", "a/b", "d.ln/b"])
        self.assert_walk_dirs(["*/*/*"], [])

    def test_remove_duplicates(self) -> None:
        self.assert_walk_files(
            ["*", "**"],
            [
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
            ],
        )
        self.assert_walk_files(
            ["**/*.txt", "a/b/1.txt", "4.txt"],
            ["4.txt", "a/3.txt", "c.ln/1.txt", "d.ln/3.txt", "a/b/1.txt", "d.ln/b/1.txt"],
        )
        self.assert_walk_dirs(["*", "**"], ["a", "c.ln", "d.ln", "a/b", "d.ln/b"])

    def test_files_content_literal(self) -> None:
        self.assert_content(["4.txt", "a/4.txt.ln"], {"4.txt": b"four\n", "a/4.txt.ln": b"four\n"})

    def test_files_content_directory(self) -> None:
        with self.assertRaises(Exception):
            self.assert_content(["a/b/"], {"a/b/": "nope\n"})
        with self.assertRaises(Exception):
            self.assert_content(["a/b"], {"a/b": "nope\n"})

    def test_files_content_symlink(self) -> None:
        self.assert_content(["c.ln/../3.txt"], {"c.ln/../3.txt": b"three\n"})

    def test_files_digest_literal(self) -> None:
        self.assert_digest(["a/3.txt", "4.txt"], ["a/3.txt", "4.txt"])

    def test_snapshot_from_outside_buildroot(self) -> None:
        with temporary_dir() as temp_dir:
            Path(temp_dir, "roland").write_text("European Burmese")
            snapshot = self.scheduler.capture_snapshots(
                (PathGlobsAndRoot(PathGlobs(["*"]), temp_dir),)
            )[0]
            self.assert_snapshot_equals(
                snapshot,
                ["roland"],
                Digest("63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16", 80),
            )

    def test_multiple_snapshots_from_outside_buildroot(self) -> None:
        with temporary_dir() as temp_dir:
            Path(temp_dir, "roland").write_text("European Burmese")
            Path(temp_dir, "susannah").write_text("I don't know")
            scheduler = self.mk_scheduler(rules=create_fs_rules())
            snapshots = scheduler.capture_snapshots(
                (
                    PathGlobsAndRoot(PathGlobs(["roland"]), temp_dir),
                    PathGlobsAndRoot(PathGlobs(["susannah"]), temp_dir),
                    PathGlobsAndRoot(PathGlobs(["doesnotexist"]), temp_dir),
                )
            )
            assert 3 == len(snapshots)
            self.assert_snapshot_equals(
                snapshots[0],
                ["roland"],
                Digest("63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16", 80),
            )
            self.assert_snapshot_equals(
                snapshots[1],
                ["susannah"],
                Digest("d3539cfc21eb4bab328ca9173144a8e932c515b1b9e26695454eeedbc5a95f6f", 82),
            )
            self.assert_snapshot_equals(snapshots[2], [], EMPTY_DIGEST)

    def test_snapshot_from_outside_buildroot_failure(self) -> None:
        with temporary_dir() as temp_dir:
            with self.assertRaises(Exception) as cm:
                self.scheduler.capture_snapshots(
                    (PathGlobsAndRoot(PathGlobs(["*"]), os.path.join(temp_dir, "doesnotexist")),)
                )
            assert "doesnotexist" in str(cm.exception)

    @staticmethod
    def assert_snapshot_equals(snapshot: Snapshot, files: List[str], digest: Digest) -> None:
        assert list(snapshot.files) == files
        assert snapshot.digest == digest

    def test_merge_zero_directories(self) -> None:
        assert self.scheduler.merge_directories(()) == EMPTY_DIGEST

    def test_synchronously_merge_directories(self) -> None:
        with temporary_dir() as temp_dir:
            Path(temp_dir, "roland").write_text("European Burmese")
            Path(temp_dir, "susannah").write_text("Not sure actually")
            (
                empty_snapshot,
                roland_snapshot,
                susannah_snapshot,
                both_snapshot,
            ) = self.scheduler.capture_snapshots(
                (
                    PathGlobsAndRoot(PathGlobs(["doesnotmatch"]), temp_dir),
                    PathGlobsAndRoot(PathGlobs(["roland"]), temp_dir),
                    PathGlobsAndRoot(PathGlobs(["susannah"]), temp_dir),
                    PathGlobsAndRoot(PathGlobs(["*"]), temp_dir),
                )
            )

            empty_merged = self.scheduler.merge_directories((empty_snapshot.digest,))
            assert empty_snapshot.digest == empty_merged

            roland_merged = self.scheduler.merge_directories(
                (roland_snapshot.digest, empty_snapshot.digest)
            )
            assert roland_snapshot.digest == roland_merged

            both_merged = self.scheduler.merge_directories(
                (roland_snapshot.digest, susannah_snapshot.digest)
            )
            assert both_snapshot.digest == both_merged

    def test_asynchronously_merge_digests(self) -> None:
        with temporary_dir() as temp_dir:
            Path(temp_dir, "roland").write_text("European Burmese")
            Path(temp_dir, "susannah").write_text("Not sure actually")
            (
                empty_snapshot,
                roland_snapshot,
                susannah_snapshot,
                both_snapshot,
            ) = self.scheduler.capture_snapshots(
                (
                    PathGlobsAndRoot(PathGlobs(["doesnotmatch"]), temp_dir),
                    PathGlobsAndRoot(PathGlobs(["roland"]), temp_dir),
                    PathGlobsAndRoot(PathGlobs(["susannah"]), temp_dir),
                    PathGlobsAndRoot(PathGlobs(["*"]), temp_dir),
                )
            )

            empty_merged = self.request_single_product(
                Digest, MergeDigests((empty_snapshot.digest,)),
            )
            assert empty_snapshot.digest == empty_merged

            roland_merged = self.request_single_product(
                Digest, MergeDigests((roland_snapshot.digest, empty_snapshot.digest)),
            )
            assert roland_snapshot.digest == roland_merged

            both_merged = self.request_single_product(
                Digest, MergeDigests((roland_snapshot.digest, susannah_snapshot.digest)),
            )
            assert both_snapshot.digest == both_merged

    def test_materialize_directories(self) -> None:
        self.prime_store_with_roland_digest()
        digest = Digest("63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16", 80)
        self.scheduler.materialize_directory(DirectoryToMaterialize(digest, path_prefix="test/"))
        assert Path(self.build_root, "test/roland").read_text() == "European Burmese"

    def test_add_prefix(self) -> None:
        input_files_content = InputFilesContent(
            (
                FileContent(path="main.py", content=b'print("from main")'),
                FileContent(path="subdir/sub.py", content=b'print("from sub")'),
            )
        )
        digest = self.request_single_product(Digest, input_files_content)
        output_digest = self.request_single_product(Digest, AddPrefix(digest, "outer_dir"))
        snapshot = self.request_single_product(Snapshot, output_digest)
        assert sorted(snapshot.files) == ["outer_dir/main.py", "outer_dir/subdir/sub.py"]
        assert sorted(snapshot.dirs) == ["outer_dir", "outer_dir/subdir"]

    def test_remove_prefix(self) -> None:
        # Set up files:
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
                os.path.join(temp_dir, "books", "dark_tower", "gunslinger"), "1982", makedirs=True,
            )

            snapshot, snapshot_with_extra_files = self.scheduler.capture_snapshots(
                (
                    PathGlobsAndRoot(PathGlobs(["characters/dark_tower/*"]), temp_dir),
                    PathGlobsAndRoot(PathGlobs(["**"]), temp_dir),
                )
            )
            # Check that we got the full snapshots that we expect
            assert snapshot.files == relevant_files
            assert snapshot_with_extra_files.files == all_files

            # Strip empty prefix:
            zero_prefix_stripped_digest = self.request_single_product(
                Digest, RemovePrefix(snapshot.digest, ""),
            )
            assert snapshot.digest == zero_prefix_stripped_digest

            # Strip a non-empty prefix shared by all files:
            stripped_digest = self.request_single_product(
                Digest, RemovePrefix(snapshot.digest, "characters/dark_tower"),
            )
            assert stripped_digest == Digest(
                fingerprint="71e788fc25783c424db555477071f5e476d942fc958a5d06ffc1ed223f779a8c",
                serialized_bytes_length=162,
            )

            expected_snapshot = assert_single_element(
                self.scheduler.capture_snapshots((PathGlobsAndRoot(PathGlobs(["*"]), tower_dir),))
            )
            assert expected_snapshot.files == ("roland", "susannah")
            assert stripped_digest == expected_snapshot.digest

            # Try to strip a prefix which isn't shared by all files:
            with self.assertRaisesWithMessageContaining(
                Exception,
                "Cannot strip prefix characters/dark_tower from root directory Digest(Fingerprint<28c47f77"
                "867f0c8d577d2ada2f06b03fc8e5ef2d780e8942713b26c5e3f434b8>, 243) - root directory "
                "contained non-matching directory named: books and file named: index",
            ):
                self.request_single_product(
                    Digest, RemovePrefix(snapshot_with_extra_files.digest, "characters/dark_tower"),
                )

    def test_lift_digest_to_snapshot(self) -> None:
        digest = self.prime_store_with_roland_digest()
        snapshot = self.request_single_product(Snapshot, digest)
        assert snapshot.files == ("roland",)
        assert snapshot.digest == digest

    def test_error_lifting_file_digest_to_snapshot(self) -> None:
        self.prime_store_with_roland_digest()

        # A file digest is not a directory digest! Hash the file that was primed as part of that
        # directory, and show that we can't turn it into a Snapshot.
        text = b"European Burmese"
        hasher = hashlib.sha256()
        hasher.update(text)
        digest = Digest(fingerprint=hasher.hexdigest(), serialized_bytes_length=len(text))

        with self.assertRaisesWithMessageContaining(ExecutionError, "unknown directory"):
            self.request_single_product(Snapshot, digest)

    def test_glob_match_error(self) -> None:
        test_name = f"{__name__}.{self.test_glob_match_error.__name__}()"
        with self.assertRaises(ValueError) as cm:
            self.assert_walk_files(
                PathGlobs(
                    globs=["not-a-file.txt"],
                    glob_match_error_behavior=GlobMatchErrorBehavior.error,
                    description_of_origin=test_name,
                ),
                [],
            )
        assert f'Unmatched glob from {test_name}: "not-a-file.txt"' in str(cm.exception)

    def test_glob_match_error_with_exclude(self) -> None:
        test_name = f"{__name__}.{self.test_glob_match_error_with_exclude.__name__}()"
        with self.assertRaises(ValueError) as cm:
            self.assert_walk_files(
                PathGlobs(
                    globs=["*.txt", "!4.txt"],
                    glob_match_error_behavior=GlobMatchErrorBehavior.error,
                    description_of_origin=test_name,
                ),
                [],
            )
        assert f'Unmatched glob from {test_name}: "*.txt", exclude: "4.txt"' in str(cm.exception)

    @unittest.skip("Skipped to expedite landing #5769: see #5863")
    def test_glob_match_warn_logging(self) -> None:
        test_name = f"{__name__}.{self.test_glob_match_warn_logging.__name__}()"
        with self.captured_logging(logging.WARNING) as captured:
            self.assert_walk_files(
                PathGlobs(
                    globs=["not-a-file.txt"],
                    glob_match_error_behavior=GlobMatchErrorBehavior.warn,
                    description_of_origin=test_name,
                ),
                [],
            )
            all_warnings = captured.warnings()
            assert len(all_warnings) == 1
            assert f'Unmatched glob from {test_name}: "not-a-file.txt"' == str(all_warnings[0])

    def test_glob_match_ignore_logging(self) -> None:
        with self.captured_logging(logging.WARNING) as captured:
            self.assert_walk_files(
                PathGlobs(
                    globs=["not-a-file.txt"],
                    glob_match_error_behavior=GlobMatchErrorBehavior.ignore,
                ),
                [],
            )
            assert len(captured.warnings()) == 0

    def prime_store_with_roland_digest(self) -> Digest:
        """This method primes the store with a directory of a file named 'roland' and contents
        'European Burmese'."""
        with temporary_dir() as temp_dir:
            with open(os.path.join(temp_dir, "roland"), "w") as f:
                f.write("European Burmese")
            globs = PathGlobs(["*"])
            snapshot = self.scheduler.capture_snapshots((PathGlobsAndRoot(globs, temp_dir),))[0]

            expected_digest = Digest(
                "63949aa823baf765eff07b946050d76ec0033144c785a94d3ebd82baa931cd16", 80
            )
            self.assert_snapshot_equals(snapshot, ["roland"], expected_digest)
        return expected_digest

    pantsbuild_digest = Digest(
        "f461fc99bcbe18e667687cf672c2dc68dc5c5db77c5bd426c9690e5c9cec4e3b", 184
    )

    def test_download(self) -> None:
        with self.isolated_local_store():
            with http_server(StubHandler) as port:
                url = UrlToFetch(
                    f"http://localhost:{port}/do_not_remove_or_edit.txt", self.pantsbuild_digest
                )
                snapshot = self.request_single_product(Snapshot, url)
                self.assert_snapshot_equals(
                    snapshot,
                    ["do_not_remove_or_edit.txt"],
                    Digest("03bb499daabafc60212d2f4b2fab49b47b35b83a90c056224c768d52bce02691", 102),
                )

    def test_download_missing_file(self) -> None:
        with self.isolated_local_store():
            with http_server(StubHandler) as port:
                url = UrlToFetch(f"http://localhost:{port}/notfound", self.pantsbuild_digest)
                with self.assertRaises(ExecutionError) as cm:
                    self.request_single_product(Snapshot, url)
                assert "404" in str(cm.exception)

    def test_download_wrong_digest(self) -> None:
        with self.isolated_local_store():
            with http_server(StubHandler) as port:
                url = UrlToFetch(
                    f"http://localhost:{port}/do_not_remove_or_edit.txt",
                    Digest(
                        self.pantsbuild_digest.fingerprint,
                        self.pantsbuild_digest.serialized_bytes_length + 1,
                    ),
                )
                with self.assertRaises(ExecutionError) as cm:
                    self.request_single_product(Snapshot, url)
                assert "wrong digest" in str(cm.exception).lower()

    # It's a shame that this isn't hermetic, but setting up valid local HTTPS certificates is a pain.
    def test_download_https(self) -> None:
        with self.isolated_local_store():
            url = UrlToFetch(
                "https://binaries.pantsbuild.org/do_not_remove_or_edit.txt",
                Digest("f461fc99bcbe18e667687cf672c2dc68dc5c5db77c5bd426c9690e5c9cec4e3b", 184,),
            )
            snapshot = self.request_single_product(Snapshot, url)
            self.assert_snapshot_equals(
                snapshot,
                ["do_not_remove_or_edit.txt"],
                Digest("03bb499daabafc60212d2f4b2fab49b47b35b83a90c056224c768d52bce02691", 102),
            )

    def test_caches_downloads(self) -> None:
        with self.isolated_local_store():
            with http_server(StubHandler) as port:
                self.prime_store_with_roland_digest()

                # This would error if we hit the HTTP server, because 404,
                # but we're not going to hit the HTTP server because it's cached,
                # so we shouldn't see an error...
                url = UrlToFetch(
                    f"http://localhost:{port}/roland",
                    Digest("693d8db7b05e99c6b7a7c0616456039d89c555029026936248085193559a0b5d", 16),
                )
                snapshot = self.request_single_product(Snapshot, url)
                self.assert_snapshot_equals(
                    snapshot,
                    ["roland"],
                    Digest("9341f76bef74170bedffe51e4f2e233f61786b7752d21c2339f8ee6070eba819", 82),
                )

    def generate_original_digest(self) -> Digest:
        content = b"dummy content"
        input_files_content = InputFilesContent(
            (
                FileContent(path="a.txt", content=content),
                FileContent(path="b.txt", content=content),
                FileContent(path="c.txt", content=content),
                FileContent(path="subdir/a.txt", content=content),
                FileContent(path="subdir/b.txt", content=content),
                FileContent(path="subdir2/a.txt", content=content),
                FileContent(path="subdir2/nested_subdir/x.txt", content=content),
            )
        )
        return self.request_single_product(Digest, input_files_content)

    def test_empty_snapshot_subset(self) -> None:
        ss = SnapshotSubset(self.generate_original_digest(), PathGlobs(()),)
        subset_snapshot = self.request_single_product(Snapshot, ss)
        assert subset_snapshot.digest == EMPTY_DIGEST
        assert subset_snapshot.files == ()
        assert subset_snapshot.dirs == ()

    def test_snapshot_subset_globs(self) -> None:
        ss = SnapshotSubset(
            self.generate_original_digest(), PathGlobs(("a.txt", "c.txt", "subdir2/**")),
        )

        subset_snapshot = self.request_single_product(Snapshot, ss)
        assert set(subset_snapshot.files) == {
            "a.txt",
            "c.txt",
            "subdir2/a.txt",
            "subdir2/nested_subdir/x.txt",
        }
        assert set(subset_snapshot.dirs) == {"subdir2/nested_subdir"}

        content = b"dummy content"
        subset_input = InputFilesContent(
            (
                FileContent(path="a.txt", content=content),
                FileContent(path="c.txt", content=content),
                FileContent(path="subdir2/a.txt", content=content),
                FileContent(path="subdir2/nested_subdir/x.txt", content=content),
            )
        )
        subset_digest = self.request_single_product(Digest, subset_input)
        assert subset_snapshot.digest == subset_digest

    def test_snapshot_subset_globs_2(self) -> None:
        ss = SnapshotSubset(
            self.generate_original_digest(), PathGlobs(("a.txt", "c.txt", "subdir2/*"))
        )

        subset_snapshot = self.request_single_product(Snapshot, ss)
        assert set(subset_snapshot.files) == {"a.txt", "c.txt", "subdir2/a.txt"}
        assert set(subset_snapshot.dirs) == {"subdir2/nested_subdir"}

    def test_nonexistent_filename_globs(self) -> None:
        # We expect to ignore, rather than error, on files that don't exist in the original snapshot.
        ss = SnapshotSubset(
            self.generate_original_digest(), PathGlobs(("some_file_not_in_snapshot.txt", "a.txt")),
        )

        subset_snapshot = self.request_single_product(Snapshot, ss)
        assert set(subset_snapshot.files) == {"a.txt"}

        content = b"dummy content"
        subset_input = InputFilesContent((FileContent(path="a.txt", content=content),))

        subset_digest = self.request_single_product(Digest, subset_input)
        assert subset_snapshot.digest == subset_digest

    def test_file_content_invalidated(self) -> None:
        """Test that we can update files and have the native engine invalidate previous operations
        on those files."""

        with self.mk_project_tree() as project_tree:
            scheduler = self.mk_scheduler(rules=create_fs_rules(), project_tree=project_tree,)
            fname = "4.txt"
            new_data = "rouf"
            # read the original file so we have a cached value.
            self.read_file_content(scheduler, [fname])
            path_to_fname = os.path.join(project_tree.build_root, fname)
            with open(path_to_fname, "w") as f:
                f.write(new_data)

            def assertion_fn() -> bool:
                new_content = self.read_file_content(scheduler, [fname])
                if new_content[fname].decode() == new_data:
                    # successfully read new data
                    return True
                return False

            if not self.try_with_backoff(assertion_fn):
                raise AssertionError(
                    f"New content {new_data} was not found in the FilesContent of the "
                    "modified file {path_to_fname}, instead we found {new_content[fname]}"
                )

    def test_file_content_invalidated_after_parent_deletion(self) -> None:
        """Test that FileContent is invalidated after deleting parent directory."""

        with self.mk_project_tree() as project_tree:
            scheduler = self.mk_scheduler(rules=create_fs_rules(), project_tree=project_tree,)
            fname = "a/b/1.txt"
            # read the original file so we have nodes to invalidate.
            original_content = self.read_file_content(scheduler, [fname])
            self.assertIn(fname, original_content)
            path_to_parent_dir = os.path.join(project_tree.build_root, "a/b/")
            shutil.rmtree(path_to_parent_dir)

            def assertion_fn():
                new_content = self.read_file_content(scheduler, [fname])
                if new_content.get(fname) is None:
                    return True
                return False

            if not self.try_with_backoff(assertion_fn):
                raise AssertionError(
                    "Deleting parent dir and could still read file from original snapshot."
                )

    def assert_mutated_digest(
        self, mutation_function: Callable[[FileSystemProjectTree, str], Exception]
    ) -> None:
        with self.mk_project_tree() as project_tree:
            scheduler = self.mk_scheduler(rules=create_fs_rules(), project_tree=project_tree,)
            dir_path = "a/"
            dir_glob = f"{dir_path}/*"
            initial_snapshot = self.execute_expecting_one_result(
                scheduler, Snapshot, PathGlobs([dir_glob])
            ).value
            assert not initial_snapshot.is_empty
            assertion_error = mutation_function(project_tree, dir_path)

            def assertion_fn() -> bool:
                new_snapshot = self.execute_expecting_one_result(
                    scheduler, Snapshot, PathGlobs([dir_glob])
                ).value
                assert not new_snapshot.is_empty
                if initial_snapshot.digest != new_snapshot.digest:
                    # successfully invalidated snapshot and got a new digest
                    return True
                return False

            if not self.try_with_backoff(assertion_fn):
                raise assertion_error

    @staticmethod
    def try_with_backoff(assertion_fn: Callable[[], bool]) -> bool:
        for i in range(4):
            time.sleep(0.1 * i)
            if assertion_fn():
                return True
        return False

    def test_digest_invalidated_by_child_removal(self) -> None:
        def mutation_function(project_tree, dir_path):
            removed_path = os.path.join(project_tree.build_root, dir_path, "3.txt")
            os.remove(removed_path)
            return AssertionError(
                f"Did not find a new directory snapshot after adding file {removed_path}."
            )

        self.assert_mutated_digest(mutation_function)

    def test_digest_invalidated_by_child_change(self) -> None:
        def mutation_function(project_tree, dir_path):
            new_file_path = os.path.join(project_tree.build_root, dir_path, "new_file.txt")
            with open(new_file_path, "w") as f:
                f.write("new file")
            return AssertionError(
                f"Did not find a new directory snapshot after adding file {new_file_path}."
            )

        self.assert_mutated_digest(mutation_function)


class StubHandler(BaseHTTPRequestHandler):
    # See https://binaries.pantsbuild.org/do_not_remove_or_edit.txt
    response_text = b"""Some tests rely on the existence of this file, with this exact content.
Edit only if you know what you're doing.

See src/python/pants/engine/fs_test.py in the pants repo for details.
"""

    def do_HEAD(self):
        self.send_headers()

    def do_GET(self):
        self.send_headers()
        self.wfile.write(self.response_text)

    def send_headers(self):
        code = 200 if self.path == "/do_not_remove_or_edit.txt" else 404
        self.send_response(code)
        self.send_header("Content-Type", "text/utf-8")
        self.send_header("Content-Length", f"{len(self.response_text)}")
        self.end_headers()
