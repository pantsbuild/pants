# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class AntlrJavaGenIntegrationTest(PantsRunIntegrationTest):

  def test_run_antlr3(self):
    stdout_data = self.bundle_and_run('examples/src/java/org/pantsbuild/example/antlr3',
                                      'examples.src.java.org.pantsbuild.example.antlr3.antlr3',
                                      bundle_jar_name='antlr3',
                                      args=['7*8'])
    self.assertEquals('56.0', stdout_data.rstrip(), msg="got output:{0}".format(stdout_data))

  def test_run_antlr4(self):
    stdout_data = self.bundle_and_run('examples/src/java/org/pantsbuild/example/antlr4',
                                      'examples.src.java.org.pantsbuild.example.antlr4.antlr4',
                                      bundle_jar_name='antlr4',
                                      args=['7*6'])
    self.assertEquals('42.0', stdout_data.rstrip(), msg="got output:{0}".format(stdout_data))
