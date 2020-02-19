# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import unittest
from functools import partial
from pathlib import Path
from typing import Optional

from pants.base.build_root import BuildRoot
from pants.fs.archive import TGZ
from pants.init.repro import Repro, Reproducer
from pants.testutil.subsystem.util import global_subsystem_instance
from pants.util.contextutil import pushd, temporary_dir
from pants.util.dirutil import safe_file_dump


class ReproTest(unittest.TestCase):
    @staticmethod
    def add_file(root: Path, relpath: str, *, content: str = "") -> None:
        full_path = Path(root, relpath)
        safe_file_dump(str(full_path), payload=content)

    def assert_file(
        self, root: Path, relpath: str, *, expected_content: Optional[str] = None
    ) -> None:
        full_path = Path(root, relpath)
        self.assertTrue(full_path.exists())
        if expected_content is not None:
            self.assertEqual(expected_content, full_path.read_text())

    def assert_not_exists(self, root: Path, relpath: str) -> None:
        self.assertFalse(Path(root, relpath).exists())

    def test_repro(self) -> None:
        """Verify that Repro object creates expected tar.gz file."""
        with temporary_dir() as tmpdir:
            fake_buildroot = Path(tmpdir, "buildroot")

            add_file = partial(self.add_file, fake_buildroot)
            add_file(".git/foo", content="foo")
            add_file("dist/bar", content="bar")
            add_file("baz.txt", content="baz")
            add_file("qux/quux.txt", content="quux")

            repro_file = Path(tmpdir, "repro.tar.gz")
            repro = Repro(str(repro_file), str(fake_buildroot), ignore=[".git", "dist"])
            repro.capture(run_info_dict={"foo": "bar", "baz": "qux"})

            extract_dir = Path(tmpdir, "extract")
            TGZ.extract(str(repro_file), str(extract_dir))

            assert_file = partial(self.assert_file, extract_dir)
            assert_file("baz.txt", expected_content="baz")
            assert_file("qux/quux.txt", expected_content="quux")
            assert_file("repro.sh")

            assert_not_exists = partial(self.assert_not_exists, extract_dir)
            assert_not_exists(".git")
            assert_not_exists("dist")

    def test_ignore_dir(self) -> None:
        """Verify that passing --repro-ignore option ignores the directory."""

        # Buildroot is is based on your cwd so we need to step into a fresh
        # directory for repro to look at.
        root_instance = BuildRoot()
        with temporary_dir() as build_root, root_instance.temporary(build_root), pushd(
            build_root
        ), temporary_dir() as capture_dir:

            add_file = partial(self.add_file, build_root)
            add_file("pants.toml")
            add_file(".git/foo", content="foo")
            add_file("dist/bar", content="bar")
            add_file("foo/bar", content="baz")
            add_file("src/test1", content="test1")
            add_file("src/test2", content="test1")

            repro_file = Path(capture_dir, "repro.tar.gz")
            options = {Reproducer.options_scope: dict(capture=str(repro_file), ignore=["src"],)}
            repro_sub = global_subsystem_instance(Reproducer, options=options)
            repro = repro_sub.create_repro()  # This is normally called in pants_exe.
            repro.capture(run_info_dict={})

            extract_loc = Path(capture_dir, "extract")
            TGZ.extract(str(repro_file), str(extract_loc))

            self.assert_file(extract_loc, "foo/bar", expected_content="baz")

            assert_not_exists = partial(self.assert_not_exists, extract_loc)
            assert_not_exists(".git")
            assert_not_exists("src")
