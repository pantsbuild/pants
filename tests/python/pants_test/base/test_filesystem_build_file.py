# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
import shutil
import tempfile
import unittest

from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern

from pants.base.build_file import BuildFile
from pants.base.file_system_project_tree import FileSystemProjectTree
from pants.base.project_tree import ProjectTree
from pants.util.dirutil import safe_mkdir, safe_open, touch
from pants.util.ordered_set import OrderedSet


class FilesystemBuildFileTest(unittest.TestCase):
    def fullpath(self, path):
        return os.path.join(self.root_dir, path)

    def makedirs(self, path):
        safe_mkdir(self.fullpath(path))

    def touch(self, path):
        touch(self.fullpath(path))

    def _create_ignore_spec(self, build_ignore_patterns):
        return PathSpec.from_lines(GitWildMatchPattern, build_ignore_patterns or [])

    def scan_buildfiles(self, base_relpath, build_ignore_patterns=None):
        return BuildFile.scan_build_files(
            self._project_tree,
            base_relpath,
            build_ignore_patterns=self._create_ignore_spec(build_ignore_patterns),
        )

    def create_buildfile(self, relpath):
        return BuildFile(self._project_tree, relpath)

    def get_build_files_family(self, relpath, build_ignore_patterns=None):
        return BuildFile.get_build_files_family(
            self._project_tree,
            relpath,
            build_ignore_patterns=self._create_ignore_spec(build_ignore_patterns),
        )

    def setUp(self):
        self.base_dir = tempfile.mkdtemp()
        # Seed a BUILD outside the build root that should not be detected
        touch(os.path.join(self.base_dir, "BUILD"))
        self.root_dir = os.path.join(self.base_dir, "root")

        self.touch("grandparent/parent/BUILD")
        self.touch("grandparent/parent/BUILD.twitter")
        # Tricky!  This is a directory
        self.makedirs("grandparent/parent/BUILD.dir")
        self.makedirs("grandparent/BUILD")
        self.touch("BUILD")
        self.touch("BUILD.twitter")
        self.touch("grandparent/parent/child1/BUILD")
        self.touch("grandparent/parent/child1/BUILD.twitter")
        self.touch("grandparent/parent/child2/child3/BUILD")
        self.makedirs("grandparent/parent/child2/BUILD")
        self.makedirs("grandparent/parent/child4")
        self.touch("grandparent/parent/child5/BUILD")
        self.makedirs("path-that-does-exist")
        self.touch("path-that-does-exist/BUILD.invalid.suffix")

        # This exercises https://github.com/pantsbuild/pants/issues/1742
        # Prior to that fix, BUILD directories were handled, but not if there was a valid BUILD file
        # sibling.
        self.makedirs("issue_1742/BUILD")
        self.touch("issue_1742/BUILD.sibling")
        self._project_tree = FileSystemProjectTree(self.root_dir)
        self.buildfile = self.create_buildfile("grandparent/parent/BUILD")

    def tearDown(self):
        shutil.rmtree(self.base_dir)

    def test_build_files_family_lookup_1(self):
        buildfile = self.create_buildfile("grandparent/parent/BUILD.twitter")
        self.assertEqual(
            {buildfile, self.buildfile}, set(self.get_build_files_family("grandparent/parent"))
        )
        self.assertEqual(
            {buildfile, self.buildfile}, set(self.get_build_files_family("grandparent/parent/"))
        )

        self.assertEqual(
            {self.create_buildfile("grandparent/parent/child2/child3/BUILD")},
            set(self.get_build_files_family("grandparent/parent/child2/child3")),
        )

    def test_build_files_family_lookup_2(self):
        self.assertEqual(
            OrderedSet(
                [
                    self.create_buildfile("grandparent/parent/BUILD"),
                    self.create_buildfile("grandparent/parent/BUILD.twitter"),
                ]
            ),
            self.get_build_files_family("grandparent/parent"),
        )

        buildfile = self.create_buildfile("grandparent/parent/child2/child3/BUILD")
        self.assertEqual(
            OrderedSet([buildfile]), self.get_build_files_family("grandparent/parent/child2/child3")
        )

    def test_build_files_family_lookup_with_ignore(self):
        self.assertEqual(
            OrderedSet([self.create_buildfile("grandparent/parent/BUILD")]),
            self.get_build_files_family("grandparent/parent", build_ignore_patterns=["*.twitter"]),
        )

    def test_build_files_scan(self):
        self.assertEqual(
            OrderedSet(
                [
                    self.create_buildfile("grandparent/parent/BUILD"),
                    self.create_buildfile("grandparent/parent/BUILD.twitter"),
                    self.create_buildfile("grandparent/parent/child1/BUILD"),
                    self.create_buildfile("grandparent/parent/child1/BUILD.twitter"),
                    self.create_buildfile("grandparent/parent/child2/child3/BUILD"),
                    self.create_buildfile("grandparent/parent/child5/BUILD"),
                ]
            ),
            self.scan_buildfiles("grandparent/parent"),
        )

    def test_build_files_scan_with_relpath_ignore(self):
        buildfiles = self.scan_buildfiles(
            "", build_ignore_patterns=["grandparent/parent/child1", "grandparent/parent/child2"]
        )
        self.assertEqual(
            OrderedSet(
                [
                    self.create_buildfile("BUILD"),
                    self.create_buildfile("BUILD.twitter"),
                    self.create_buildfile("grandparent/parent/BUILD"),
                    self.create_buildfile("grandparent/parent/BUILD.twitter"),
                    self.create_buildfile("grandparent/parent/child5/BUILD"),
                    self.create_buildfile("issue_1742/BUILD.sibling"),
                ]
            ),
            buildfiles,
        )

        buildfiles = self.scan_buildfiles(
            "grandparent/parent", build_ignore_patterns=["grandparent/parent/child1"]
        )
        self.assertEqual(
            OrderedSet(
                [
                    self.create_buildfile("grandparent/parent/BUILD"),
                    self.create_buildfile("grandparent/parent/BUILD.twitter"),
                    self.create_buildfile("grandparent/parent/child2/child3/BUILD"),
                    self.create_buildfile("grandparent/parent/child5/BUILD"),
                ]
            ),
            buildfiles,
        )

    def test_build_files_scan_with_abspath_ignore(self):
        self.touch("parent/BUILD")
        self.assertEqual(
            OrderedSet(
                [
                    self.create_buildfile("BUILD"),
                    self.create_buildfile("BUILD.twitter"),
                    self.create_buildfile("grandparent/parent/BUILD"),
                    self.create_buildfile("grandparent/parent/BUILD.twitter"),
                    self.create_buildfile("grandparent/parent/child1/BUILD"),
                    self.create_buildfile("grandparent/parent/child1/BUILD.twitter"),
                    self.create_buildfile("grandparent/parent/child2/child3/BUILD"),
                    self.create_buildfile("grandparent/parent/child5/BUILD"),
                    self.create_buildfile("issue_1742/BUILD.sibling"),
                ]
            ),
            self.scan_buildfiles("", build_ignore_patterns=["/parent"]),
        )

    def test_build_files_scan_with_wildcard_ignore(self):
        self.assertEqual(
            OrderedSet(
                [
                    self.create_buildfile("BUILD"),
                    self.create_buildfile("BUILD.twitter"),
                    self.create_buildfile("grandparent/parent/BUILD"),
                    self.create_buildfile("grandparent/parent/BUILD.twitter"),
                    self.create_buildfile("issue_1742/BUILD.sibling"),
                ]
            ),
            self.scan_buildfiles("", build_ignore_patterns=["**/child*"]),
        )

    def test_build_files_scan_with_ignore_patterns(self):
        self.assertEqual(
            OrderedSet(
                [
                    self.create_buildfile("BUILD"),
                    self.create_buildfile("grandparent/parent/BUILD"),
                    self.create_buildfile("grandparent/parent/child1/BUILD"),
                    self.create_buildfile("grandparent/parent/child2/child3/BUILD"),
                    self.create_buildfile("grandparent/parent/child5/BUILD"),
                    self.create_buildfile("issue_1742/BUILD.sibling"),
                ]
            ),
            self.scan_buildfiles("", build_ignore_patterns=["BUILD.twitter"]),
        )

    def test_subdir_ignore(self):
        self.touch("grandparent/child1/BUILD")

        self.assertEqual(
            OrderedSet(
                [
                    self.create_buildfile("BUILD"),
                    self.create_buildfile("BUILD.twitter"),
                    self.create_buildfile("grandparent/child1/BUILD"),
                    self.create_buildfile("grandparent/parent/BUILD"),
                    self.create_buildfile("grandparent/parent/BUILD.twitter"),
                    self.create_buildfile("grandparent/parent/child2/child3/BUILD"),
                    self.create_buildfile("grandparent/parent/child5/BUILD"),
                    self.create_buildfile("issue_1742/BUILD.sibling"),
                ]
            ),
            self.scan_buildfiles("", build_ignore_patterns=["**/parent/child1"]),
        )

    def test_subdir_file_pattern_ignore(self):
        self.assertEqual(
            OrderedSet(
                [
                    self.create_buildfile("BUILD"),
                    self.create_buildfile("grandparent/parent/BUILD"),
                    self.create_buildfile("grandparent/parent/child1/BUILD"),
                    self.create_buildfile("grandparent/parent/child2/child3/BUILD"),
                    self.create_buildfile("grandparent/parent/child5/BUILD"),
                ]
            ),
            self.scan_buildfiles("", build_ignore_patterns=["BUILD.*"]),
        )

    def test_build_files_scan_with_non_default_relpath_ignore(self):
        self.assertEqual(
            OrderedSet(
                [
                    self.create_buildfile("grandparent/parent/BUILD"),
                    self.create_buildfile("grandparent/parent/BUILD.twitter"),
                    self.create_buildfile("grandparent/parent/child2/child3/BUILD"),
                    self.create_buildfile("grandparent/parent/child5/BUILD"),
                ]
            ),
            self.scan_buildfiles("grandparent/parent", build_ignore_patterns=["**/parent/child1"]),
        )

    def test_must_exist_true(self):
        with self.assertRaises(BuildFile.MissingBuildFileError):
            self.create_buildfile("path-that-does-not-exist/BUILD")
        with self.assertRaises(BuildFile.MissingBuildFileError):
            self.create_buildfile("path-that-does-exist/BUILD")
        with self.assertRaises(BuildFile.MissingBuildFileError):
            self.create_buildfile("path-that-does-exist/BUILD.invalid.suffix")

    def test_suffix_only(self):
        self.makedirs("suffix-test")
        self.touch("suffix-test/BUILD.suffix")
        self.touch("suffix-test/BUILD.suffix2")
        self.makedirs("suffix-test/child")
        self.touch("suffix-test/child/BUILD.suffix3")
        buildfile = self.create_buildfile("suffix-test/BUILD.suffix")
        self.assertEqual(
            OrderedSet([buildfile, self.create_buildfile("suffix-test/BUILD.suffix2")]),
            OrderedSet(self.get_build_files_family("suffix-test")),
        )
        self.assertEqual(
            OrderedSet(
                [
                    self.create_buildfile("suffix-test/BUILD.suffix"),
                    self.create_buildfile("suffix-test/BUILD.suffix2"),
                ]
            ),
            self.get_build_files_family("suffix-test"),
        )
        self.assertEqual(
            OrderedSet([self.create_buildfile("suffix-test/child/BUILD.suffix3")]),
            self.scan_buildfiles("suffix-test/child"),
        )

    def test_directory_called_build_skipped(self):
        # Ensure the buildfiles found do not include grandparent/BUILD since it is a dir.
        buildfiles = self.scan_buildfiles("grandparent")

        self.assertEqual(
            OrderedSet(
                [
                    self.create_buildfile("grandparent/parent/BUILD"),
                    self.create_buildfile("grandparent/parent/BUILD.twitter"),
                    self.create_buildfile("grandparent/parent/child1/BUILD"),
                    self.create_buildfile("grandparent/parent/child1/BUILD.twitter"),
                    self.create_buildfile("grandparent/parent/child2/child3/BUILD"),
                    self.create_buildfile("grandparent/parent/child5/BUILD"),
                ]
            ),
            buildfiles,
        )

    def test_dir_is_primary(self):
        self.assertEqual(
            [self.create_buildfile("issue_1742/BUILD.sibling")],
            list(self.get_build_files_family("issue_1742")),
        )

    def test_invalid_root_dir_error(self):
        self.touch("BUILD")
        with self.assertRaises(ProjectTree.InvalidBuildRootError):
            BuildFile(FileSystemProjectTree("tmp"), "grandparent/BUILD")

    def test_exception_class_hierarchy(self):
        """Exception handling code depends on the fact that all exceptions from BuildFile are
        subclassed from the BuildFileError base class."""
        self.assertIsInstance(BuildFile.MissingBuildFileError(), BuildFile.BuildFileError)

    def test_code(self):
        with safe_open(self.fullpath("BUILD.code"), "w") as fp:
            fp.write('lib = java_library(name="jake", age=42)')
        build_file = self.create_buildfile("BUILD.code")

        parsed_locals = {}
        exec(build_file.code(), {"java_library": dict}, parsed_locals)
        lib = parsed_locals.pop("lib", None)
        self.assertEqual(dict(name="jake", age=42), lib)

    def test_code_syntax_error(self):
        with safe_open(self.fullpath("BUILD.badsyntax"), "w") as fp:
            fp.write("java_library(name=if)")
        build_file = self.create_buildfile("BUILD.badsyntax")
        with self.assertRaises(SyntaxError) as e:
            build_file.code()
        self.assertEqual(build_file.full_path, e.exception.filename)
