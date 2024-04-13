# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

import errno
import os
import unittest
import unittest.mock
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator

import pytest

from pants.util import dirutil
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import (
    _mkdtemp_unregister_cleaner,
    absolute_symlink,
    fast_relpath,
    find_nearest_ancestor_file,
    group_by_dir,
    longest_dir_prefix,
    read_file,
    relative_symlink,
    rm_rf,
    safe_concurrent_creation,
    safe_file_dump,
    safe_mkdir,
    safe_mkdtemp,
    safe_open,
    safe_rmtree,
    touch,
)


def strict_patch(target, **kwargs):
    return unittest.mock.patch(target, autospec=True, spec_set=True, **kwargs)


class TestDirutilTest:
    @pytest.fixture(autouse=True)
    def _setup(self) -> None:
        # Ensure we start in a clean state.
        _mkdtemp_unregister_cleaner()

    def test_longest_dir_prefix(self) -> None:
        # Find the longest prefix (standard case).
        prefixes = ["hello", "hello_world", "hello/world", "helloworld"]
        assert longest_dir_prefix("hello/world/pants", prefixes) == "hello/world"
        assert longest_dir_prefix("hello/", prefixes) == "hello"
        assert longest_dir_prefix("hello", prefixes) == "hello"
        assert longest_dir_prefix("scoobydoobydoo", prefixes) is None

    def test_longest_dir_prefix_special(self) -> None:
        # Ensure that something that is a longest prefix, but not a longest dir
        # prefix, is not tagged.
        prefixes = ["helloworldhowareyou", "helloworld"]
        assert longest_dir_prefix("helloworldhowareyoufine/", prefixes) is None
        assert longest_dir_prefix("helloworldhowareyoufine", prefixes) is None

    def test_fast_relpath(self) -> None:
        def assert_relpath(expected: str, path: str, start: str) -> None:
            assert expected == fast_relpath(path, start)

        assert_relpath("c", "/a/b/c", "/a/b")
        assert_relpath("c", "/a/b/c", "/a/b/")
        assert_relpath("c", "b/c", "b")
        assert_relpath("c", "b/c", "b/")
        assert_relpath("c/", "b/c/", "b")
        assert_relpath("c/", "b/c/", "b/")
        assert_relpath("", "c/", "c/")
        assert_relpath("", "c", "c")
        assert_relpath("", "c/", "c")
        assert_relpath("", "c", "c/")
        assert_relpath("c/", "c/", "")
        assert_relpath("c", "c", "")

    def test_fast_relpath_invalid(self) -> None:
        with pytest.raises(ValueError):
            fast_relpath("/a/b", "/a/baseball")
        with pytest.raises(ValueError):
            fast_relpath("/a/baseball", "/a/b")

    @strict_patch("atexit.register")
    @strict_patch("os.getpid")
    @strict_patch("pants.util.dirutil.safe_rmtree")
    @strict_patch("tempfile.mkdtemp")
    def test_mkdtemp_setup_teardown(
        self, tempfile_mkdtemp, dirutil_safe_rmtree, os_getpid, atexit_register
    ):
        def faux_cleaner():
            pass

        DIR1, DIR2 = "fake_dir1__does_not_exist", "fake_dir2__does_not_exist"

        # Make sure other "pids" are not cleaned.
        dirutil._MKDTEMP_DIRS["fluffypants"].add("yoyo")

        tempfile_mkdtemp.side_effect = (DIR1, DIR2)
        os_getpid.return_value = "unicorn"
        try:
            assert DIR1 == dirutil.safe_mkdtemp(dir="1", cleaner=faux_cleaner)
            assert DIR2 == dirutil.safe_mkdtemp(dir="2", cleaner=faux_cleaner)
            assert "unicorn" in dirutil._MKDTEMP_DIRS
            assert {DIR1, DIR2} == dirutil._MKDTEMP_DIRS["unicorn"]
            dirutil._mkdtemp_atexit_cleaner()
            assert "unicorn" not in dirutil._MKDTEMP_DIRS
            assert {"yoyo"} == dirutil._MKDTEMP_DIRS["fluffypants"]
        finally:
            dirutil._MKDTEMP_DIRS.pop("unicorn", None)
            dirutil._MKDTEMP_DIRS.pop("fluffypants", None)
            dirutil._mkdtemp_unregister_cleaner()

        atexit_register.assert_called_once_with(faux_cleaner)
        assert os_getpid.called
        assert [
            unittest.mock.call(dir="1"),
            unittest.mock.call(dir="2"),
        ] == tempfile_mkdtemp.mock_calls
        assert sorted([unittest.mock.call(DIR1), unittest.mock.call(DIR2)]) == sorted(
            dirutil_safe_rmtree.mock_calls
        )

    def test_safe_walk(self) -> None:
        """Test that directory names are correctly represented as unicode strings."""
        # This test is unnecessary in python 3 since all strings are unicode there is no
        # unicode constructor.
        with temporary_dir() as tmpdir:
            safe_mkdir(os.path.join(tmpdir, "中文"))
            for _, dirs, _ in dirutil.safe_walk(tmpdir.encode()):
                assert all(isinstance(dirname, str) for dirname in dirs)

    @contextmanager
    def tree(self) -> Iterator[tuple[str, str]]:
        # root/
        #   a/
        #     b/
        #       1
        #       2
        #     2 -> root/a/b/2
        #   b -> root/a/b
        with temporary_dir() as root:
            with safe_open(os.path.join(root, "a", "b", "1"), "wb") as fp:
                fp.write(b"1")
            touch(os.path.join(root, "a", "b", "2"))
            os.symlink(os.path.join(root, "a", "b", "2"), os.path.join(root, "a", "2"))
            os.symlink(os.path.join(root, "a", "b"), os.path.join(root, "b"))
            with temporary_dir() as dst:
                yield root, dst

    @dataclass(frozen=True)
    class Dir:
        path: str

    @dataclass(frozen=True)
    class File:
        path: str
        contents: str

        @classmethod
        def empty(cls, path: str) -> TestDirutilTest.File:
            return cls(path, contents="")

        @classmethod
        def read(cls, root: str, relpath: str) -> TestDirutilTest.File:
            with open(os.path.join(root, relpath)) as fp:
                return cls(relpath, fp.read())

    @dataclass(frozen=True)
    class Symlink:
        path: str

    def assert_tree(self, root: str, *expected: Dir | File | Symlink):
        def collect_tree() -> (
            Iterator[TestDirutilTest.Dir | TestDirutilTest.File | TestDirutilTest.Symlink]
        ):
            for path, dirnames, filenames in os.walk(root, followlinks=False):
                relpath = os.path.relpath(path, root)
                if relpath == os.curdir:
                    relpath = ""
                for dirname in dirnames:
                    dirpath = os.path.join(relpath, dirname)
                    if os.path.islink(os.path.join(path, dirname)):
                        yield self.Symlink(dirpath)
                    else:
                        yield self.Dir(dirpath)
                for filename in filenames:
                    filepath = os.path.join(relpath, filename)
                    if os.path.islink(os.path.join(path, filename)):
                        yield self.Symlink(filepath)
                    else:
                        yield self.File.read(root, filepath)

        assert frozenset(expected) == frozenset(collect_tree())

    def test_relative_symlink(self) -> None:
        with temporary_dir() as tmpdir_1:  # source and link in same dir
            source = os.path.join(tmpdir_1, "source")
            link = os.path.join(tmpdir_1, "link")
            rel_path = os.path.relpath(source, os.path.dirname(link))
            relative_symlink(source, link)
            assert os.path.islink(link)
            assert rel_path == os.readlink(link)

    def test_relative_symlink_source_parent(self) -> None:
        with temporary_dir() as tmpdir_1:  # source in parent dir of link
            child = os.path.join(tmpdir_1, "child")
            os.mkdir(child)
            source = os.path.join(tmpdir_1, "source")
            link = os.path.join(child, "link")
            relative_symlink(source, link)
            rel_path = os.path.relpath(source, os.path.dirname(link))
            assert os.path.islink(link)
            assert rel_path == os.readlink(link)

    def test_relative_symlink_link_parent(self) -> None:
        with temporary_dir() as tmpdir_1:  # link in parent dir of source
            child = os.path.join(tmpdir_1, "child")
            source = os.path.join(child, "source")
            link = os.path.join(tmpdir_1, "link")
            relative_symlink(source, link)
            rel_path = os.path.relpath(source, os.path.dirname(link))
            assert os.path.islink(link)
            assert rel_path == os.readlink(link)

    def test_relative_symlink_same_paths(self) -> None:
        with temporary_dir() as tmpdir_1:  # source is link
            source = os.path.join(tmpdir_1, "source")
            with pytest.raises(ValueError, match=r"Path for link is identical to source"):
                relative_symlink(source, source)

    def test_relative_symlink_bad_source(self) -> None:
        with temporary_dir() as tmpdir_1:  # source is not absolute
            source = os.path.join("foo", "bar")
            link = os.path.join(tmpdir_1, "link")
            with pytest.raises(ValueError, match=r"Path for source.*absolute"):
                relative_symlink(source, link)

    def test_relative_symlink_bad_link(self) -> None:
        with temporary_dir() as tmpdir_1:  # link is not absolute
            source = os.path.join(tmpdir_1, "source")
            link = os.path.join("foo", "bar")
            with pytest.raises(ValueError, match=r"Path for link.*absolute"):
                relative_symlink(source, link)

    def test_relative_symlink_overwrite_existing_file(self) -> None:
        # Succeeds, since os.unlink can be safely called on files that aren't symlinks.
        with temporary_dir() as tmpdir_1:  # source and link in same dir
            source = os.path.join(tmpdir_1, "source")
            link_path = os.path.join(tmpdir_1, "link")
            touch(link_path)
            relative_symlink(source, link_path)

    def test_relative_symlink_exception_on_existing_dir(self) -> None:
        # This historically was an uncaught exception, the tested behavior is to begin catching the error.
        with temporary_dir() as tmpdir_1:
            source = os.path.join(tmpdir_1, "source")
            link_path = os.path.join(tmpdir_1, "link")

            safe_mkdir(link_path)
            with pytest.raises(
                ValueError, match=r"Path for link.*overwrite an existing directory*"
            ):
                relative_symlink(source, link_path)

    def test_rm_rf_file(self, file_name="./foo") -> None:
        with temporary_dir() as td, pushd(td):
            touch(file_name)
            assert os.path.isfile(file_name)
            rm_rf(file_name)
            assert not os.path.exists(file_name)

    def test_rm_rf_dir(self, dir_name="./bar") -> None:
        with temporary_dir() as td, pushd(td):
            safe_mkdir(dir_name)
            assert os.path.isdir(dir_name)
            rm_rf(dir_name)
            assert not os.path.exists(dir_name)

    def test_rm_rf_nonexistent(self, file_name="./non_existent_file") -> None:
        with temporary_dir() as td, pushd(td):
            rm_rf(file_name)

    def test_rm_rf_permission_error_raises(self, file_name="./perm_guarded_file") -> None:
        with temporary_dir() as td, pushd(td), unittest.mock.patch(
            "pants.util.dirutil.shutil.rmtree"
        ) as mock_rmtree, pytest.raises(OSError):
            mock_rmtree.side_effect = OSError(errno.EACCES, os.strerror(errno.EACCES))
            touch(file_name)
            rm_rf(file_name)

    def test_rm_rf_no_such_file_not_an_error(self, file_name="./vanishing_file") -> None:
        with temporary_dir() as td, pushd(td), unittest.mock.patch(
            "pants.util.dirutil.shutil.rmtree"
        ) as mock_rmtree:
            mock_rmtree.side_effect = OSError(errno.ENOENT, os.strerror(errno.ENOENT))
            touch(file_name)
            rm_rf(file_name)

    def assert_dump_and_read(self, test_content, dump_kwargs, read_kwargs):
        with temporary_dir() as td:
            test_filename = os.path.join(td, "test.out")
            safe_file_dump(test_filename, test_content, **dump_kwargs)
            assert read_file(test_filename, **read_kwargs) == test_content

    def test_readwrite_file_binary(self) -> None:
        self.assert_dump_and_read(b"333", {"mode": "wb"}, {"binary_mode": True})
        with pytest.raises(Exception):
            # File is not opened as binary.
            self.assert_dump_and_read(b"333", {"mode": "w"}, {"binary_mode": True})

    def test_readwrite_file_unicode(self) -> None:
        self.assert_dump_and_read("✓", {"mode": "w"}, {"binary_mode": False})
        with pytest.raises(Exception):
            # File is opened as binary.
            self.assert_dump_and_read("✓", {"mode": "wb"}, {"binary_mode": True})

    def test_safe_concurrent_creation(self) -> None:
        with temporary_dir() as td:
            expected_file = os.path.join(td, "expected_file")
            with safe_concurrent_creation(expected_file) as tmp_expected_file:
                os.mkdir(tmp_expected_file)
                assert os.path.exists(tmp_expected_file)
                assert not os.path.exists(expected_file)
            assert os.path.exists(expected_file)

    def test_safe_concurrent_creation_noop(self) -> None:
        with temporary_dir() as td:
            expected_file = os.path.join(td, "parent_dir", "expected_file")

            # Ensure safe_concurrent_creation() doesn't bomb if we don't write the expected files.
            with safe_concurrent_creation(expected_file):
                pass

            assert not os.path.exists(expected_file)
            assert os.path.exists(os.path.dirname(expected_file))

    def test_safe_concurrent_creation_exception_handling(self) -> None:
        with temporary_dir() as td:
            expected_file = os.path.join(td, "expected_file")

            with pytest.raises(ZeroDivisionError):
                with safe_concurrent_creation(expected_file) as safe_path:
                    os.mkdir(safe_path)
                    assert os.path.exists(safe_path)
                    raise ZeroDivisionError("zomg")

            assert not os.path.exists(safe_path)
            assert not os.path.exists(expected_file)

    def test_safe_rmtree_link(self):
        with temporary_dir() as td:
            real = os.path.join(td, "real")
            link = os.path.join(td, "link")
            os.mkdir(real)
            os.symlink(real, link)
            assert os.path.exists(real)
            assert os.path.exists(link)
            safe_rmtree(link)
            assert os.path.exists(real)
            assert not os.path.exists(link)

    def test_group_by_dir(self) -> None:
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


class AbsoluteSymlinkTest(unittest.TestCase):
    def setUp(self) -> None:
        self.td = safe_mkdtemp()
        self.addCleanup(safe_rmtree, self.td)

        self.source = os.path.join(self.td, "source")
        self.link = os.path.join(self.td, "link")

    def _create_and_check_link(self, source: str, link: str) -> None:
        absolute_symlink(source, link)
        assert os.path.islink(link)
        assert source == os.readlink(link)

    def test_link(self) -> None:
        # Check if parent dirs will be created for the link
        link = os.path.join(self.td, "a", "b", "c", "self.link")
        self._create_and_check_link(self.source, link)

    def test_overwrite_link_link(self) -> None:
        # Do it twice, to make sure we can overwrite existing link
        self._create_and_check_link(self.source, self.link)
        self._create_and_check_link(self.source, self.link)

    def test_overwrite_link_file(self) -> None:
        with open(self.source, "w") as fp:
            fp.write("evidence")

        # Do it twice, to make sure we can overwrite existing link
        self._create_and_check_link(self.source, self.link)
        self._create_and_check_link(self.source, self.link)

        # The link should have been deleted (over-written), not the file it pointed to.
        with open(self.source) as fp:
            assert "evidence" == fp.read()

    def test_overwrite_link_dir(self) -> None:
        nested_dir = os.path.join(self.source, "a", "b", "c")
        os.makedirs(nested_dir)

        # Do it twice, to make sure we can overwrite existing link
        self._create_and_check_link(self.source, self.link)
        self._create_and_check_link(self.source, self.link)

        # The link should have been deleted (over-written), not the dir it pointed to.
        assert os.path.isdir(nested_dir)

    def test_overwrite_file(self) -> None:
        touch(self.link)
        self._create_and_check_link(self.source, self.link)

    def test_overwrite_dir(self) -> None:
        os.makedirs(os.path.join(self.link, "a", "b", "c"))
        self._create_and_check_link(self.source, self.link)


def test_find_nearest_ancestor_file() -> None:
    files = {"grok.conf", "foo/bar/grok.conf", "hello/world/grok.conf"}
    assert find_nearest_ancestor_file(files, "foo/bar", "grok.conf") == "foo/bar/grok.conf"
    assert find_nearest_ancestor_file(files, "foo/bar/", "grok.conf") == "foo/bar/grok.conf"
    assert find_nearest_ancestor_file(files, "foo", "grok.conf") == "grok.conf"
    assert find_nearest_ancestor_file(files, "foo/", "grok.conf") == "grok.conf"
    assert find_nearest_ancestor_file(files, "foo/xyzzy", "grok.conf") == "grok.conf"
    assert find_nearest_ancestor_file(files, "foo/xyzzy", "grok.conf") == "grok.conf"
    assert find_nearest_ancestor_file(files, "", "grok.conf") == "grok.conf"
    assert find_nearest_ancestor_file(files, "hello", "grok.conf") == "grok.conf"
    assert find_nearest_ancestor_file(files, "hello/", "grok.conf") == "grok.conf"
    assert (
        find_nearest_ancestor_file(files, "hello/world/foo", "grok.conf") == "hello/world/grok.conf"
    )
    assert (
        find_nearest_ancestor_file(files, "hello/world/foo/", "grok.conf")
        == "hello/world/grok.conf"
    )

    files2 = {"foo/bar/grok.conf", "hello/world/grok.conf"}
    assert find_nearest_ancestor_file(files2, "foo", "grok.conf") is None
    assert find_nearest_ancestor_file(files2, "foo/", "grok.conf") is None
    assert find_nearest_ancestor_file(files2, "", "grok.conf") is None
