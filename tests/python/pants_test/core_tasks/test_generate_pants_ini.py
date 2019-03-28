# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import configparser

from pants.base.exceptions import TaskError
from pants.core_tasks.generate_pants_ini import GeneratePantsIni
from pants.version import VERSION
from pants_test.task_test_base import TaskTestBase


class GeneratePantsIniIntegration(TaskTestBase):

  @classmethod
  def task_type(cls):
    return GeneratePantsIni

  def setUp(self):
    super(GeneratePantsIniIntegration, self).setUp()
    self.temp_pants_ini_path = self.create_file("pants.ini")
    self.task = self.create_task(self.context())

  def test_pants_ini_generated_when_empty(self):
    self.task.execute()
    config = configparser.ConfigParser()
    config.read(self.temp_pants_ini_path)
    self.assertEqual(config["GLOBAL"]["pants_version"], VERSION)
    self.assertIn(config["GLOBAL"]["pants_runtime_python_version"], {"2.7", "3.6", "3.7"})

  def test_fails_when_pants_ini_is_not_empty(self):
    with open(self.temp_pants_ini_path, "w") as f:
      f.write("[GLOBAL]")
    with self.assertRaisesWithMessageContaining(TaskError, self.temp_pants_ini_path):
      self.task.execute()
