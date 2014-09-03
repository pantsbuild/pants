# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import re

from pants.util.contextutil import temporary_dir

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class IvyResolveIntegrationTest(PantsRunIntegrationTest):

  def _assert_run_success(self, pants_run):
    self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                      "goal compile expected success, got {0}\n"
                      "got stderr:\n{1}\n"
                      "got stdout:\n{2}\n".format(pants_run.returncode,
                                                  pants_run.stderr_data,
                                                  pants_run.stdout_data))

  def test_java_compile_with_ivy_report(self):
    # Ensure the ivy report file gets generated
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      ivy_report_dir = '{workdir}/ivy-report'.format(workdir=workdir)
      pants_run = self.run_pants_with_workdir(
        ['goal', 'compile', 'testprojects/src/java/com/pants/testproject/unicode/main',
         '--ivy-report', '--ivy-outdir={reportdir}'.format(reportdir=ivy_report_dir)], workdir)
      self._assert_run_success(pants_run)

      # Find the ivy report
      found = False
      pattern = re.compile('internal-[a-f0-9]+-default\.html$')
      for f in os.listdir(ivy_report_dir):
        if os.path.isfile(os.path.join(ivy_report_dir, f)):
          if pattern.match(f):
            found = True
            break
      self.assertTrue(found,
                      msg="Couldn't find ivy report in {report_dir}"
                      .format(report_dir=ivy_report_dir))
