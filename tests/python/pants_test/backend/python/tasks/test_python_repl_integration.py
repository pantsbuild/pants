# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_daemon


class PythonReplIntegrationTest(PantsRunIntegrationTest):

  @ensure_daemon
  def test_run_repl(self):
    # Run a repl on a library target. Avoid some known-to-choke-on interpreters.
    command = ['repl',
               'testprojects/src/python/interpreter_selection:echo_interpreter_version_lib',
               '--python-setup-interpreter-constraints=CPython>=2.7,<3',
               '--python-setup-interpreter-constraints=CPython>=3.3',
               '--quiet']
    program = 'from interpreter_selection.echo_interpreter_version import say_hello; say_hello()'
    pants_run = self.run_pants(command=command, stdin_data=program)
    output_lines = pants_run.stdout_data.rstrip().split('\n')
    self.assertIn('echo_interpreter_version loaded successfully.', output_lines)
