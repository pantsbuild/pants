# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import unittest

from pants.base.build_root import BuildRoot
from pants.util.contextutil import environment_as, pushd, temporary_dir
from pants.util.dirutil import safe_mkdir, safe_mkdtemp, safe_rmtree, touch


class BuildRootTest(unittest.TestCase):
    def setUp(self) -> None:
        self.build_root = BuildRoot()
        self.original_path = self.build_root.path
        self.new_path = os.path.realpath(safe_mkdtemp())
        self.build_root.reset()

    def tearDown(self) -> None:
        self.build_root.reset()
        safe_rmtree(self.new_path)

    def test_via_set(self) -> None:
        self.build_root.path = self.new_path
        self.assertEqual(self.new_path, self.build_root.path)

    def test_reset(self) -> None:
        self.build_root.path = self.new_path
        self.build_root.reset()
        self.assertEqual(self.original_path, self.build_root.path)

    def test_via_pants_runner(self) -> None:
        with temporary_dir() as root:
            root = os.path.realpath(root)
            touch(os.path.join(root, "BUILD_ROOT"))
            with pushd(root):
                self.assertEqual(root, self.build_root.path)

            self.build_root.reset()
            child = os.path.join(root, "one", "two")
            safe_mkdir(child)
            with pushd(child):
                self.assertEqual(root, self.build_root.path)

    def test_temporary(self) -> None:
        with self.build_root.temporary(self.new_path):
            self.assertEqual(self.new_path, self.build_root.path)
        self.assertEqual(self.original_path, self.build_root.path)

    def test_singleton(self) -> None:
        self.assertEqual(BuildRoot().path, BuildRoot().path)
        BuildRoot().path = self.new_path
        self.assertEqual(BuildRoot().path, BuildRoot().path)

    def test_not_found(self) -> None:
        with temporary_dir() as root:
            root = os.path.realpath(root)
            with pushd(root):
                self.assertRaises(BuildRoot.NotFoundError, lambda: self.build_root.path)

    def test_buildroot_override(self) -> None:
        with temporary_dir() as root:
            with environment_as(PANTS_BUILDROOT_OVERRIDE=root):
                self.assertEqual(self.build_root.path, root)
