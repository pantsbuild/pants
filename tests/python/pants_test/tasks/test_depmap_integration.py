# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import re

from pants.util.contextutil import temporary_dir

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class DepmapIntegrationTest(PantsRunIntegrationTest):

  def _assert_run_success(self, pants_run):
    self.assertEquals(pants_run.returncode, self.PANTS_SUCCESS_CODE,
                      'goal depmap expected success, got {0}\n'
                      'got stderr:\n{1}\n'
                      'got stdout:\n{2}\n'.format(pants_run.returncode,
                                                  pants_run.stderr_data,
                                                  pants_run.stdout_data))

  def test_depmap_with_resolve(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      depmap_out_file = '{workdir}/depmap_out.txt'.format(workdir=workdir)
      pants_run = self.run_pants_with_workdir(
        ['goal', 'resolve', 'depmap', 'testprojects/src/java/com/pants/testproject/unicode/main',
         '--depmap-project-info',
         '--depmap-output-file={out_file}'.format(out_file=depmap_out_file)], workdir)
      self._assert_run_success(pants_run)
      self.assertTrue(os.path.exists(depmap_out_file),
                      msg='Couldn't find depmap output file in {out_file}'
                      .format(out_file=depmap_out_file))

    #TODO:(tdesai) Test the file contents.

  def test_depmap_without_resolve(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      depmap_out_file = '{workdir}/depmap_out.txt'.format(workdir=workdir)
      pants_run = self.run_pants_with_workdir(
        ['goal', 'depmap', 'testprojects/src/java/com/pants/testproject/unicode/main',
         '--depmap-project-info',
         '--depmap-output-file={out_file}'.format(out_file=depmap_out_file)], workdir)
      self._assert_run_success(pants_run)
      self.assertTrue(os.path.exists(depmap_out_file),
                      msg='Couldn't find depmap output file {out_file}'
                      .format(out_file=depmap_out_file))
