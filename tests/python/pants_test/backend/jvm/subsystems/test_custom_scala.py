# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants.backend.jvm.subsystems.scala_platform import ScalaPlatform
from pants.backend.jvm.targets.jar_library import JarLibrary
from pants.backend.jvm.targets.scala_library import ScalaLibrary
from pants.backend.jvm.tasks.scalastyle import Scalastyle
from pants.java.jar.jar_dependency import JarDependency
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase
from pants_test.subsystem.subsystem_util import init_subsystem


class CustomScalaTest(NailgunTaskTestBase):
  @classmethod
  def task_type(cls):
    return Scalastyle

  def setUp(self):
    super(CustomScalaTest, self).setUp()
    self.context()  # We don't need the context, but this ensures subsystem option registration.

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

  def _create_context(self, scalastyle_config=None, excludes=None, target_roots=None):
    # If config is not specified, then we override pants.ini scalastyle such that
    # we have a default scalastyle config xml but with empty excludes.
    self.set_options(skip=False, config=scalastyle_config, excludes=excludes)
    return self.context(target_roots=target_roots)

  def _create_scalastyle_config_file(self, rules=None):
    # put a default rule there if rules are not specified.
    rules = rules or ['org.scalastyle.scalariform.ImportGroupingChecker']
    rule_section_xml = ''
    for rule in rules:
      rule_section_xml += dedent("""
        <check level="error" class="{rule}" enabled="true"></check>
      """.format(rule=rule))
    return self.create_file(
      relpath='scalastyle_config.xml',
      contents=dedent("""
        <scalastyle commentFilter="enabled">
          <name>Test Scalastyle configuration</name>
          {rule_section_xml}
        </scalastyle>
      """.format(rule_section_xml=rule_section_xml)))

  def scala_platform_setup(self):
    options = {
      ScalaPlatform.options_scope: {
        'version': 'custom',
        'suffix_version': '2.10',
      }
    }
    init_subsystem(ScalaPlatform, options)

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

  def test_custom_lib_spec(self):
    self.scala_platform_setup()
    self.make_target('//:scala-library',
                     JarLibrary,
                     jars=[JarDependency('org.scala-lang', 'scala-library', '2.10.5')])
    scala_target = self.make_target('a/scala:pass', ScalaLibrary, sources=['pass.scala'])

    context = self._create_context(
        scalastyle_config=self._create_scalastyle_config_file(),
        target_roots=[scala_target]
    )

    self.execute(context)

  def test_no_custom_target(self):
    with self.assertRaises(ValueError):
      # This should raise:
      # ValueError: Tests must make targets for traversable dependency specs
      # ahead of them being traversed, ScalaLibrary(a/scala:pass) tried to traverse
      # //:scala-library-custom which does not exist.
      self.scala_platform_setup()
      scala_target = self.make_target('a/scala:pass', ScalaLibrary, sources=['pass.scala'])

      context = self._create_context(
          scalastyle_config=self._create_scalastyle_config_file(),
          target_roots=[scala_target]
      )

      self.execute(context)
