# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import json
import os

from pants.util.contextutil import temporary_dir

from pants.ivy.bootstrapper import Bootstrapper
from pants.base.build_environment import get_buildroot
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
      test_target = 'examples/tests/java/com/pants/examples/usethrift:usethrift'
      pants_run = self.run_pants_with_workdir(
        ['goal', 'resolve', 'depmap', test_target, '--depmap-project-info',
         '--depmap-output-file={out_file}'.format(out_file=depmap_out_file)], workdir)
      self._assert_run_success(pants_run)
      self.assertTrue(os.path.exists(depmap_out_file),
                      msg='Could not find depmap output file in {out_file}'
                           .format(out_file=depmap_out_file))
      with open(depmap_out_file) as json_file:
        json_data = json.load(json_file)
        targets = json_data['targets']
        libraries = json_data['libraries']
        # check single code gen module is listed in the target
        thrift_target_name = 'examples.src.thrift.com.pants.examples.precipitation.precipitation-java'
        codegen_target = os.path.join(os.path.relpath(workdir,get_buildroot()),
                                      'gen/thrift/combined/gen-java:%s' %thrift_target_name)
        self.assertTrue(codegen_target in targets)
        # check if transitively pulled in jar exists as dependency
        self.assertTrue('org.hamcrest:hamcrest-core:1.3' in targets[test_target]['libraries'])
        #check correct library path.
        ivy_cache_dir = Bootstrapper.instance().ivy_cache_dir
        self.assertEquals(libraries['commons-lang:commons-lang:2.5'],
                          [os.path.join(ivy_cache_dir,
                                        'commons-lang/commons-lang/jars/commons-lang-2.5.jar')])

  def test_depmap_without_resolve(self):
    with temporary_dir(root_dir=self.workdir_root()) as workdir:
      depmap_out_file = '{workdir}/depmap_out.txt'.format(workdir=workdir)
      pants_run = self.run_pants_with_workdir(
        ['goal', 'depmap', 'testprojects/src/java/com/pants/testproject/unicode/main',
         '--depmap-project-info',
         '--depmap-output-file={out_file}'.format(out_file=depmap_out_file)], workdir)
      self._assert_run_success(pants_run)
      self.assertTrue(os.path.exists(depmap_out_file),
                      msg='Could not find depmap output file {out_file}'
                           .format(out_file=depmap_out_file))
