# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from textwrap import dedent

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.subsystems.scoverage_platform import ScoveragePlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.java.jar.jar_dependency import JarDependency
from pants.testutil.subsystem.util import init_subsystem
from pants.testutil.test_base import TestBase


class ScoveragePlatformTest(TestBase):
    scoverage_path = "//:scoverage"
    blacklist_file_path = "my/file/new_blacklist_scoverage_test"

    def setup_scoverage_platform(self):
        options = {ScalaPlatform.options_scope: {"version": "custom", "suffix_version": "2.10"}}

        options2 = {ScoveragePlatform.options_scope: {"enable_scoverage": "False"}}

        init_subsystem(ScalaPlatform, options)
        init_subsystem(ScoveragePlatform, options2)

        self.make_target(
            "//:scalastyle",
            JarLibrary,
            jars=[JarDependency("org.scalastyle", "scalastyle_2.10", "0.3.2")],
        )

        self.make_target(
            "//:scala-repl",
            JarLibrary,
            jars=[
                JarDependency(org="org.scala-lang", name="jline", rev="2.10.5"),
                JarDependency(org="org.scala-lang", name="scala-compiler", rev="2.10.5"),
            ],
        )

        self.make_target(
            "//:scalac",
            JarLibrary,
            jars=[JarDependency("org.scala-lang", "scala-compiler", "2.10.5")],
        )

        self.make_target(
            "//:scala-library",
            JarLibrary,
            jars=[JarDependency("org.scala-lang", "scala-library", "2.10.5")],
        )

    # ==========> TESTS <=============
    # ================================
    def test_subsystem_defaults(self):
        init_subsystem(ScoveragePlatform)

        subsystem = ScoveragePlatform.global_instance()

        self.assertEqual(False, subsystem.get_options().enable_scoverage)

    def test_subsystem_option_sets(self):
        init_subsystem(ScoveragePlatform)
        ScoveragePlatform.global_instance().get_options().enable_scoverage = True

        subsystem = ScoveragePlatform.global_instance()

        self.assertEqual(True, subsystem.get_options().enable_scoverage)

    def test_library_scoverage_enabled(self):
        self.setup_scoverage_platform()
        ScoveragePlatform.global_instance().get_options().enable_scoverage = True

        self.create_file(
            relpath="a/scala/pass.scala",
            contents=dedent(
                """
                import java.util
                object HelloWorld {
                   def main(args: Array[String]) {
                      println("Hello, world!")
                   }
                }
                """
            ),
        )

        scala_target = self.make_target("a/scala:pass", ScalaLibrary, sources=["pass.scala"])

        self.assertIn("scoverage", scala_target.scalac_plugins)
        self.assertIn("scoverage", scala_target.scalac_plugin_args)
        self.assertIn(
            "//:scoverage", list(map(lambda t: t.address.spec, scala_target.dependencies))
        )
        self.assertIn("scoverage", list(scala_target.compiler_option_sets))

    def test_library_scoverage_disabled(self):
        self.setup_scoverage_platform()
        ScoveragePlatform.global_instance().get_options().enable_scoverage = False

        self.create_file(
            relpath="a/scala/pass.scala",
            contents=dedent(
                """
                import java.util
                object HelloWorld {
                   def main(args: Array[String]) {
                      println("Hello, world!")
                   }
                }
                """
            ),
        )

        scala_target = self.make_target("a/scala:pass", ScalaLibrary, sources=["pass.scala"])

        self.assertNotIn("scoverage", scala_target.scalac_plugins)
        if scala_target.scalac_plugin_args:
            self.assertNotIn("scoverage", scala_target.scalac_plugin_args)
        self.assertNotIn(
            "//:scoverage", list(map(lambda t: t.address.spec, scala_target.dependencies))
        )
        if scala_target.compiler_option_sets:
            self.assertNotIn("scoverage", list(scala_target.compiler_option_sets))

    def test_blacklist(self):
        """When a target is blacklisted, we do not instrument it.

        For achieving that, we only
        want `scalac_plugins` to not contain `scoverage`. Thus, the target may still have
        `scoverage` in `scalac_plugin_args` and in `dependencies` but it will not be
        instrumented as long as `scalac_plugins` do not contain `scoverage`.
        :return:
        """
        self.setup_scoverage_platform()
        ScoveragePlatform.global_instance().get_options().enable_scoverage = True
        ScoveragePlatform.global_instance().get_options().blacklist_targets = ["blacked"]

        self.create_file(
            relpath="a/scala/pass.scala",
            contents=dedent(
                """
                import java.util
                object HelloWorld {
                   def main(args: Array[String]) {
                      println("Hello, world!")
                   }
                }
                """
            ),
        )

        scala_target = self.make_target("a/scala:blacked", ScalaLibrary, sources=["pass.scala"])

        self.assertNotIn("scoverage", scala_target.scalac_plugins)
