# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from textwrap import dedent

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PythonReplIntegrationTest(PantsRunIntegrationTest):

  def test_run_repl(self):
    # Run a repl on a library target. Avoid some known-to-choke-on interpreters.
    command = ['goal', 'repl', 'src/scala/com/pants/example/hello/welcome',
               '--interpreter=CPython>=2.6,<3',
               '--interpreter=CPython>=3.3', '--quiet']
    program = dedent("""import com.pants.example.hello.welcome.WelcomeEverybody
                        println(WelcomeEverybody("World" :: Nil).head)
                     """)
    pants_run = self.run_pants(command=command, stdin_data=program)
    output_lines = pants_run.stdout_data.rstrip().split('\n')
    self.assertEquals(len(output_lines), 11)
    print('XXXX %s' % output_lines)
    self.assertEquals('Hello, World!', output_lines[-3])

