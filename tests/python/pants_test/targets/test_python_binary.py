# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants.backend.python.register import build_file_aliases
from pants.base.exceptions import TargetDefinitionException
from pants.testutil.test_base import TestBase


class TestPythonBinary(TestBase):
    @classmethod
    def alias_groups(self):
        return build_file_aliases()

    def setUp(self):
        super().setUp()
        # Force creation of SourceRootConfig global instance. PythonBinary uses source roots
        # when computing entry points.
        self.context()

    def test_python_binary_must_have_some_entry_point(self):
        self.add_to_build_file("", 'python_binary(name = "binary")')
        with self.assertRaises(TargetDefinitionException):
            self.target(":binary")

    def test_python_binary_with_entry_point_no_source(self):
        self.add_to_build_file("", 'python_binary(name = "binary", entry_point = "blork")')
        assert self.target(":binary").entry_point == "blork"

    def test_python_binary_with_source_no_entry_point(self):
        self.create_file("blork.py")
        self.create_file("bin/blork.py")
        self.add_to_build_file(
            "",
            """python_binary(
  name = "binary1",
  sources = ["blork.py"],
)

python_binary(
  name = "binary2",
  sources = ["bin/blork.py"],
)""",
        )
        assert self.target(":binary1").entry_point == "blork"
        assert self.target(":binary2").entry_point == "bin.blork"

    def test_python_binary_with_entry_point_and_source(self):
        self.create_file("blork.py")
        self.create_file("bin/blork.py")
        self.add_to_build_file(
            "",
            """python_binary(
  name = "binary1",
  entry_point = "blork",
  sources = ["blork.py"],
)

python_binary(
  name = "binary2",
  entry_point = "blork:main",
  sources = ["blork.py"],
)

python_binary(
  name = "binary3",
  entry_point = "bin.blork:main",
  sources = ["bin/blork.py"],
)""",
        )

        assert "blork" == self.target(":binary1").entry_point
        assert "blork:main" == self.target(":binary2").entry_point
        assert "bin.blork:main" == self.target(":binary3").entry_point

    def test_python_binary_with_entry_point_and_source_mismatch(self):
        self.create_file("binary1/hork.py")
        self.add_to_build_file(
            "binary1", 'python_binary(entry_point = "blork", sources = ["hork.py"])',
        )
        with self.assertRaises(TargetDefinitionException):
            self.target("binary1")

        self.create_file("binary2/hork.py")
        self.add_to_build_file(
            "binary2", 'python_binary(entry_point = "blork:main", sources = ["hork.py"])',
        )
        with self.assertRaises(TargetDefinitionException):
            self.target("binary2")

        self.create_file("binary3/blork.py")
        self.add_to_build_file(
            "binary3", 'python_binary(entry_point = "bin.blork", sources = ["blork.py"])',
        )
        with self.assertRaises(TargetDefinitionException):
            self.target("binary3")

        self.create_file("binary4/bin.py")
        self.add_to_build_file(
            "binary4", 'python_binary(entry_point = "bin.blork", sources = ["bin.py"])',
        )
        with self.assertRaises(TargetDefinitionException):
            self.target("binary4")
