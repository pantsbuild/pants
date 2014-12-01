# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class AntlrIntegrationTest(PantsRunIntegrationTest):
  def test_run_antlr3(self):
    stdout_data = self.bundle_and_run('examples/src/java/com/pants/examples/antlr3', 'antlr3',
                                      args=['7*8'])
    self.assertEquals('56.0', stdout_data.rstrip(), msg="got output:{0}".format(stdout_data))

  def test_run_antlr4(self):
    stdout_data = self.bundle_and_run('examples/src/java/com/pants/examples/antlr4', 'antlr4',
                                      args=['7*6'])
    self.assertEquals('42.0', stdout_data.rstrip(), msg="got output:{0}".format(stdout_data))
