# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ScalaReplIntegrationTest(PantsRunIntegrationTest):

  def run_repl(self, target, program):
    """Run a repl for the given target with the given input, and return stdout_data"""
    # Run a repl on a library target. Avoid some known-to-choke-on interpreters.
    command = ['repl',
               target,
               '--interpreter=CPython>=2.6,<3',
               '--interpreter=CPython>=3.3',
               '--quiet']
    pants_run = self.run_pants(command=command, stdin_data=program)
    self.assert_success(pants_run)
    return pants_run.stdout_data.rstrip().split('\n')

  def test_run_repl_direct(self):
    output_lines = self.run_repl('examples/src/scala/org/pantsbuild/example/hello/welcome', dedent("""\
      import org.pantsbuild.example.hello.welcome.WelcomeEverybody
      println(WelcomeEverybody("World" :: Nil).head)
      """))
    self.assertEquals(len(output_lines), 12)
    self.assertEquals('Hello, World!', output_lines[-3])

  def test_run_repl_transitive(self):
    output_lines = self.run_repl('testprojects/src/scala/org/pantsbuild/testproject/unicode', dedent("""\
      println(org.pantsbuild.testproject.unicode.shapeless.ShapelessExample.greek())
      """))
    self.assertTrue("shapeless success" in output_lines)
