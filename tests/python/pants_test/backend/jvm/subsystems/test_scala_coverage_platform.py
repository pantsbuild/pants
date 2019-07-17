from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
  unicode_literals, with_statement)

from pants_test.test_base import TestBase
from pants_test.subsystem.subsystem_util import init_subsystem
from pants.backend.jvm.subsystems.scala_coverage_platform import ScalaCoveragePlatform
from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.java.jar.jar_dependency import JarDependency


from textwrap import dedent


class ScalaCoveragePlatformTest(TestBase):
  scoverage_path = '//:scoverage'

  def setup_scala_coverage_platform(self):
    options = {
      ScalaPlatform.options_scope: {
        'version': 'custom',
        'suffix_version': '2.10',
      }
    }

    options2 = {
      ScalaCoveragePlatform.options_scope: {
        'enable_scoverage' : 'False'
      }
    }

    init_subsystem(ScalaPlatform, options)
    init_subsystem(ScalaCoveragePlatform, options2)

    self.make_target('//:scalastyle',
      JarLibrary,
      jars=[JarDependency('org.scalastyle', 'scalastyle_2.10', '0.3.2')]
    )

    self.make_target('//:scala-repl',
      JarLibrary,
      jars=[
        JarDependency(org = 'org.scala-lang',
          name = 'jline',
          rev = '2.10.5'),
        JarDependency(org = 'org.scala-lang',
          name = 'scala-compiler',
          rev = '2.10.5')])

    self.make_target('//:scalac',
      JarLibrary,
      jars=[JarDependency('org.scala-lang', 'scala-compiler', '2.10.5')])

    self.make_target('//:scala-library',
      JarLibrary,
      jars=[JarDependency('org.scala-lang', 'scala-library', '2.10.5')])

    self.make_target('//:scoverage',
      JarLibrary,
      jars=[JarDependency('com.twitter.scoverage', 'scalac-scoverage-plugin', '1.0.1-twitter'),
        JarDependency('com.twitter.scoverage', 'scalac-scoverage-runtime', '1.0.1-twitter')])


  # ==========> TESTS <=============
  # ================================
  def test_subsystem_defaults(self):
    init_subsystem(ScalaCoveragePlatform)

    subsystem = ScalaCoveragePlatform.global_instance()

    self.assertEqual(False, subsystem.get_options().enable_scoverage)
    self.assertEqual(self.scoverage_path, subsystem.get_options().scoverage_target_path)

  def test_subsystem_option_sets(self):
    init_subsystem(ScalaCoveragePlatform)
    ScalaCoveragePlatform.global_instance().get_options().enable_scoverage = True

    subsystem = ScalaCoveragePlatform.global_instance()

    self.assertEqual(True, subsystem.get_options().enable_scoverage)
    self.assertEqual(self.scoverage_path, subsystem.get_options().scoverage_target_path)


  def test_library_scoverage_enabled(self):
    self.setup_scala_coverage_platform()
    ScalaCoveragePlatform.global_instance().get_options().enable_scoverage = True

    self.create_file(
      relpath='a/scala/pass.scala',
      contents=dedent("""
        import java.util
        object HelloWorld {
           def main(args: Array[String]) {
              println("Hello, world!")
           }
        }
      """))

    scala_target = self.make_target('a/scala:pass', ScalaLibrary, sources=['pass.scala'])

    self.assertIn('scoverage', scala_target.scalac_plugins)
    self.assertIn('scoverage', scala_target.scalac_plugin_args)
    self.assertIn('//:scoverage', list(map(lambda t: t.address.spec, scala_target.dependencies)))
    self.assertIn('scoverage', list(scala_target.compiler_option_sets))


  def test_library_scoverage_disabled(self):
    self.setup_scala_coverage_platform()
    ScalaCoveragePlatform.global_instance().get_options().enable_scoverage = False

    self.create_file(
      relpath='a/scala/pass.scala',
      contents=dedent("""
        import java.util
        object HelloWorld {
           def main(args: Array[String]) {
              println("Hello, world!")
           }
        }
      """))

    scala_target = self.make_target('a/scala:pass', ScalaLibrary, sources=['pass.scala'])

    self.assertNotIn('scoverage', scala_target.scalac_plugins)
    if scala_target.scalac_plugin_args:
      self.assertNotIn('scoverage', scala_target.scalac_plugin_args)
    self.assertNotIn('//:scoverage', list(map(lambda t: t.address.spec ,scala_target.dependencies)))
    if scala_target.compiler_option_sets:
      self.assertNotIn('scoverage', list(scala_target.compiler_option_sets))


  def test_blacklist(self):
    """
    When a target is blacklisted, we do not instrument it. For achieving that, we only
    want `scalac_plugins` to not contain `scoverage`. Thus, the target may still have
    `scoverage` in `scalac_plugin_args` and in `dependencies` but it will not be
    instrumented as long as `scalac_plugins` do not contain `scoverage`.
    :return:
    """
    self.setup_scala_coverage_platform()
    ScalaCoveragePlatform.global_instance().get_options().enable_scoverage = True

    blacklist_file = open("new_blacklist_scoverage", "a+")
    blacklist_file.write("a/scala:blacked")

    self.create_file(
      relpath='a/scala/pass.scala',
      contents=dedent("""
        import java.util
        object HelloWorld {
           def main(args: Array[String]) {
              println("Hello, world!")
           }
        }
      """))

    scala_target = self.make_target('a/scala:blacked', ScalaLibrary, sources=['pass.scala'])

    self.assertNotIn('scoverage', scala_target.scalac_plugins)

