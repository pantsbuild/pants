# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ScalaReplIntegrationTest(PantsRunIntegrationTest):

  def run_repl(self, target, program):
    """Run a repl for the given target with the given input, and return stdout_data"""
    # Run a repl on a library target. Avoid some known-to-choke-on interpreters.
    command = ['goal', 'repl', target,
               '--interpreter=CPython>=2.6,<3',
               '--interpreter=CPython>=3.3', '--quiet']
    pants_run = self.run_pants(command=command, stdin_data=program)
    self.assert_success(pants_run)
    return pants_run.stdout_data.rstrip().split('\n')

  def test_run_repl_direct(self):
    output_lines = self.run_repl('examples/src/scala/com/pants/example/hello/welcome', dedent("""\
      import com.pants.example.hello.welcome.WelcomeEverybody
      println(WelcomeEverybody("World" :: Nil).head)
      """))
    self.assertEquals(len(output_lines), 11)
    self.assertEquals('Hello, World!', output_lines[-3])

  def test_run_repl_transitive(self):
    output_lines = self.run_repl('testprojects/src/scala/com/pants/testproject/unicode', dedent("""\
      println(com.pants.testproject.unicode.shapeless.ShapelessExample.greek())
      """))
    self.assertTrue("shapeless success" in output_lines)
