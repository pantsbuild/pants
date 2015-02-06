# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class IvyResolveIntegrationTest(PantsRunIntegrationTest):

  def test_ivy_resolve_gives_correct_exception_on_cycles(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      pants_run = self.run_pants_with_workdir([
          'compile', 'testprojects/src/java/com/pants/testproject/cycle1'], workdir)
      self.assert_failure(pants_run)
      self.assertTrue('CycleException' in pants_run.stderr_data)

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

  def test_ivy_args(self):
    pants_run = self.run_pants([
        'resolve',
        '--resolve-ivy-args=-blablabla',
        'examples/src/scala::'
    ])
    self.assert_failure(pants_run)
    self.assertTrue('Unrecognized option: -blablabla' in pants_run.stdout_data)

  def test_ivy_confs_success(self):
    pants_run = self.run_pants([
        'resolve',
        '--resolve-ivy-confs=default',
        '--resolve-ivy-confs=sources',
        '--resolve-ivy-confs=javadoc',
        '3rdparty:junit'
    ])
    self.assert_success(pants_run)

  def test_ivy_confs_failure(self):
    pants_run = self.run_pants([
        'resolve',
        '--resolve-ivy-confs=parampampam',
        '3rdparty:junit'
    ])
    self.assert_failure(pants_run)

  def test_ivy_confs_ini_failure(self):
    pants_ini_config = {'resolve.ivy': {'confs': 'parampampam'}}
    pants_run = self.run_pants([
        'resolve',
        '3rdparty:junit'
    ], config=pants_ini_config)
    self.assert_failure(pants_run)
