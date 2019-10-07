# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.jvm.register import build_file_aliases as register_jvm
from pants.backend.jvm.targets.java_library import JavaLibrary
from pants.base.exceptions import TaskError
from pants.build_graph.register import build_file_aliases as register_core
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase

from pants.contrib.googlejavaformat.googlejavaformat import (
    GoogleJavaFormat,
    GoogleJavaFormatCheckFormat,
)


class TestBase(NailgunTaskTestBase):

    _BADFORMAT = dedent(
        """
    package org.pantsbuild.contrib.googlejavaformat;
    class MyClass {
        public static void main(String[] args) {
            System.out.println("Hello google-java-format!");
        }
    }
    """
    )

    _GOODFORMAT = dedent(
        """\
    package org.pantsbuild.contrib.googlejavaformat;
    
    class MyClass {
      public static void main(String[] args) {
        System.out.println("Hello google-java-format!");
      }
    }
  """
    )

    @classmethod
    def alias_groups(cls):
        return super().alias_groups().merge(register_core().merge(register_jvm()))


class GoogleJavaFormatTests(TestBase):
    @classmethod
    def task_type(cls):
        return GoogleJavaFormat

    def test_googlejavaformat(self):
        javafile = self.create_file(
            relpath="src/java/org/pantsbuild/contrib/googlejavaformat/MyClass.java",
            contents=self._BADFORMAT,
        )
        target = self.make_target(
            spec="src/java/org/pantsbuild/contrib/googlejavaformat",
            target_type=JavaLibrary,
            sources=["MyClass.java"],
        )
        context = self.context(target_roots=[target])
        self.execute(context)
        with open(javafile, "r") as fh:
            actual = fh.read()
        self.assertEqual(actual, self._GOODFORMAT)


class GoogleJavaFormatCheckFormatTests(TestBase):
    @classmethod
    def task_type(cls):
        return GoogleJavaFormatCheckFormat

    def test_lint_badformat(self):
        self.create_file(
            relpath="src/java/org/pantsbuild/contrib/googlejavaformat/MyClass.java",
            contents=self._BADFORMAT,
        )
        target = self.make_target(
            spec="src/java/org/pantsbuild/contrib/googlejavaformat",
            target_type=JavaLibrary,
            sources=["MyClass.java"],
        )
        context = self.context(target_roots=[target])
        with self.assertRaises(TaskError) as error:
            self.execute(context)
        self.assertEqual(
            str(error.exception),
            "google-java-format failed with exit code 1; to fix run: `./pants fmt <targets>`",
        )

    def test_lint_goodformat(self):
        self.create_file(
            relpath="src/java/org/pantsbuild/contrib/googlejavaformat/MyClass.java",
            contents=self._GOODFORMAT,
        )
        target = self.make_target(
            spec="src/java/org/pantsbuild/contrib/googlejavaformat",
            target_type=JavaLibrary,
            sources=["MyClass.java"],
        )
        context = self.context(target_roots=[target])
        self.execute(context)
