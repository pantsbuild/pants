# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestScalaLibraryIntegrationTest(PantsRunIntegrationTest):
  def test_bundle(self):
    pants_run = self.run_pants(['goal', 'compile', 'src/scala/com/pants/testproject/javasources'])
    self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                      "goal compile expected success, got {0}\n"
                      "got stderr:\n{1}\n"
                      "got stdout:\n{2}\n".format(pants_run.returncode,
                                                  pants_run.stderr_data,
                                                  pants_run.stdout_data))
