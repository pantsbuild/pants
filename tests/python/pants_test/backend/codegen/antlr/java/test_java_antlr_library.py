# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.codegen.antlr.java.java_antlr_library import JavaAntlrLibrary
from pants.base.exceptions import TargetDefinitionException
from pants.build_graph.build_file_aliases import BuildFileAliases
from pants.testutil.test_base import TestBase


class JavaAntlrLibraryTest(TestBase):
    @classmethod
    def alias_groups(cls):
        return BuildFileAliases(targets={"java_antlr_library": JavaAntlrLibrary})

    def test_empty(self):
        with self.assertRaisesRegex(
            TargetDefinitionException, "the sources parameter.*contains an empty snapshot."
        ):
            self.add_to_build_file(
                "BUILD",
                dedent(
                    """
        java_antlr_library(name='foo',
          sources=[],
        )"""
                ),
            )
            self.foo = self.target("//:foo")

    def test_valid(self):
        self.create_file(self.build_path("something.txt"), contents="asdf", mode="w")
        self.add_to_build_file(
            "BUILD",
            dedent(
                """
      java_antlr_library(name='foo',
        sources=['something.txt'],
      )"""
            ),
        )
        self.foo = self.target("//:foo")
        self.assertIsInstance(self.foo, JavaAntlrLibrary)

    def test_invalid_compiler(self):
        with self.assertRaisesRegex(TargetDefinitionException, "Illegal value for 'compiler'"):
            self.add_to_build_file(
                "BUILD",
                dedent(
                    """
        java_antlr_library(name='foo',
          sources=['foo'],
          compiler='antlr9'
        )"""
                ),
            )
            self.foo = self.target("//:foo")
