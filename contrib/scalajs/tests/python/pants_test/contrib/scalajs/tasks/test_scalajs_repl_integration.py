# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class ScalaJSReplIntegrationTest(PantsRunIntegrationTest):

  def test_run_repl(self):
    command = ['-q',
               'repl',
               'contrib/scalajs/examples/src/scalajs/org/pantsbuild/example/factfinder']
    program = dedent("""
        var _ = require('factfinder');
        org.pantsbuild.example.factfinder.Main().main();
      """)
    pants_run = self.run_pants(command=command, stdin_data=program)

    self.assert_success(pants_run)
    self.assertEqual('Hello from ScalaJS! 3628800', pants_run.stdout_data.strip())
