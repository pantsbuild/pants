# coding=utf-8
# Copyright 2018 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import OrderedDict

from pants.base.build_environment import get_buildroot
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class PantsRequirementIntegrationTest(PantsRunIntegrationTest):

  def run_with_testproject_backend_pkgs(self, cmd):
    testproject_backend_src_dir = os.path.join(
      get_buildroot(), 'testprojects/pants-plugins/src/python')
    testproject_backend_pkg_name = 'test_pants_plugin'
    pants_req_addr = 'testprojects/pants-plugins/3rdparty/pants'
    pants_test_infra_addr = 'tests/python/pants_test:test_infra'
    pre_cmd_args = [
      "--pythonpath=+['{}']".format(testproject_backend_src_dir),
      "--backend-packages=+['{}']".format(testproject_backend_pkg_name),
      "--python-test-infra-pants-requirement-target={}".format(pants_req_addr),
      "--python-test-infra-pants-test-infra-target={}".format(pants_test_infra_addr),
    ]
    command = pre_cmd_args + cmd
    return self.run_pants(command=command)

  def test_pants_requirement(self):
    self.maxDiff = None

    command = [
      'test',
      'testprojects/pants-plugins/tests/python/test_pants_plugin',
    ]
    pants_run = self.run_with_testproject_backend_pkgs(command)
    self.assert_success(pants_run)
