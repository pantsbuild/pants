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

  def test_java_compile_with_ivy_report(self):
    # Ensure the ivy report file gets generated
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      ivy_report_dir = '{workdir}/ivy-report'.format(workdir=workdir)
      pants_run = self.run_pants_with_workdir([
          'compile',
          'testprojects/src/java/com/pants/testproject/unicode/main',
          '--resolve-ivy-report',
          '--resolve-ivy-outdir={reportdir}'.format(reportdir=ivy_report_dir)],
          workdir)
      self.assert_success(pants_run)

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
