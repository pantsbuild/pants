# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import configparser
import os
from builtins import open
from contextlib import contextmanager

from pants.core_tasks.generate_pants_ini import GeneratePantsIni
from pants.version import VERSION
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class GeneratePantsIniIntegration(PantsRunIntegrationTest):

  @contextmanager
  def temporarily_remove_pants_ini_content(self):
    os.rename(GeneratePantsIni.PANTS_INI, "{}.orig".format(GeneratePantsIni.PANTS_INI))
    open(GeneratePantsIni.PANTS_INI, "w").close()
    try:
      yield
    finally:
      os.rename("{}.orig".format(GeneratePantsIni.PANTS_INI), GeneratePantsIni.PANTS_INI)

  def test_pants_ini_generated_when_missing(self):
    with self.temporarily_remove_pants_ini_content():
      pants_run = self.run_pants(["generate-pants-ini"])
      self.assert_success(pants_run)
      config = configparser.ConfigParser()
      config.read(GeneratePantsIni.PANTS_INI)
      self.assertEqual(config["GLOBAL"]["pants_version"], VERSION)
      self.assertIn(config["GLOBAL"]["pants_runtime_python_version"], {"2.7", "3.6", "3.7"})

  def test_fails_when_pants_ini_present(self):
    self.assertTrue(os.path.isfile(GeneratePantsIni.PANTS_INI))
    pants_run = self.run_pants(["generate-pants-ini"])
    self.assert_failure(pants_run)
    self.assertIn("already", pants_run.stdout_data)     
