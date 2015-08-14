# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ScalaReplIntegrationTest(PantsRunIntegrationTest):

  def run_repl(self, target, program, repl_args=None):
    """Run a repl for the given target with the given input, and return stdout_data"""
    command = ['repl']
    if repl_args:
      command.extend(repl_args)
    command.extend([target, '--quiet'])
    pants_run = self.run_pants(command=command, stdin_data=program)
    self.assert_success(pants_run)
    return pants_run.stdout_data.splitlines()

  def run_repl_helloworld(self, repl_args=None):
    output_lines = self.run_repl(
        'examples/src/scala/org/pantsbuild/example/hello/welcome',
        dedent("""
            import org.pantsbuild.example.hello.welcome.WelcomeEverybody
            println(WelcomeEverybody("World" :: Nil).head)
          """),
        repl_args=repl_args)
    return output_lines

  def test_run_repl_direct(self):
    self.assertIn('Hello, World!', self.run_repl_helloworld())

  def test_run_repl_explicit_usejavacp(self):
    self.assertIn('Hello, World!',
                  self.run_repl_helloworld(repl_args=['--jvm-options=-Dscala.usejavacp=true']))

  def test_run_repl_explicit_nousejavacp(self):
    self.assertIn('Failed to initialize the REPL due to an unexpected error.',
                  self.run_repl_helloworld(repl_args=['--jvm-options=-Dscala.usejavacp=false']))

  def test_run_repl_transitive(self):
    output_lines = self.run_repl(
      'testprojects/src/scala/org/pantsbuild/testproject/unicode',
      dedent("""
          import org.pantsbuild.testproject.unicode.shapeless.ShapelessExample
          println(ShapelessExample.greek())
        """))
    self.assertIn("shapeless success", output_lines)
