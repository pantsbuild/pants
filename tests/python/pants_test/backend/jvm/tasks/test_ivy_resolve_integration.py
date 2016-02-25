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
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
          'compile', 'testprojects/src/java/org/pantsbuild/testproject/cycle1'], workdir)
      self.assert_failure(pants_run)
      self.assertIn('Cycle detected', pants_run.stderr_data)

  def test_java_compile_with_ivy_report(self):
    # Ensure the ivy report file gets generated
    with self.temporary_workdir() as workdir:
      ivy_report_dir = '{workdir}/ivy-report'.format(workdir=workdir)
      pants_run = self.run_pants_with_workdir([
          'compile',
          'testprojects/src/java/org/pantsbuild/testproject/unicode/main',
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
    self.assertIn('Unrecognized option: -blablabla', pants_run.stdout_data)

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

  def test_ivy_bimodal_resolve_caching(self):
    # This test covers the case where a successful ivy resolve will drop a generic representation
    # and cache it. Then, after a clean-all invalidates the workdir, the next resolve will use the
    # version information from the previous, rather than doing a full resolve.

    with self.temporary_workdir() as workdir, temporary_dir() as cache_dir:
      config = {'cache': {'write_to': [cache_dir],'read_from': [cache_dir]}}

      def run_pants(command):
        return self.run_pants_with_workdir(command, workdir, config=config)

      first_export_result = run_pants(['export', '3rdparty:junit'])

      resolve_workdir = self._find_resolve_workdir(workdir)
      # The first run did a ran ivy in resolve mode, so it doesn't have a fetch-ivy.xml.
      self.assertNotIn('fetch-ivy.xml', os.listdir(resolve_workdir))

      run_pants(['clean-all'])

      run_pants(['export', '3rdparty:junit'])
      second_export_result = run_pants(['export', '3rdparty:junit'])

      # Using the fetch pattern should result in the same export information.
      self.assertEqual(first_export_result.stdout_data, second_export_result.stdout_data)

      # The second run uses the cached resolution information from the first resolve, and
      # generates a fetch ivy.xml.
      self.assertIn('fetch-ivy.xml', os.listdir(resolve_workdir))

  def _find_resolve_workdir(self, workdir):
    # Finds the first resolve workdir that contains a resolution.json.
    # Otherwise fails
    ivy_dir = os.path.join(workdir, 'ivy')
    listdir = os.listdir(ivy_dir)
    listdir.remove('jars')
    for dir in listdir:
      potential_workdir = os.path.join(ivy_dir, dir)
      if os.path.exists(os.path.join(potential_workdir, 'resolution.json')):
        #print(potential_workdir)
        return potential_workdir
    else:
      self.fail("No resolution.json in ivy workdirs")
