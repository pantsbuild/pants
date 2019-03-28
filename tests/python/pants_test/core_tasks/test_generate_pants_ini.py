# coding=utf-8
# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import absolute_import, division, print_function, unicode_literals

import configparser

from pants.base.exceptions import TaskError
from pants.core_tasks.generate_pants_ini import GeneratePantsIni
from pants.version import VERSION
from pants_test.task_test_base import ConsoleTaskTestBase


class GeneratePantsIniTest(ConsoleTaskTestBase):

  @classmethod
  def task_type(cls):
    return GeneratePantsIni

  def test_pants_ini_generated_when_empty(self):
    temp_pants_ini_path = self.create_file("pants.ini")
    self.execute_task()
    config = configparser.ConfigParser()
    config.read(temp_pants_ini_path)
    self.assertEqual(config["GLOBAL"]["pants_version"], VERSION)
    self.assertIn(config["GLOBAL"]["pants_runtime_python_version"], {"2.7", "3.6", "3.7"})

  def test_fails_when_pants_ini_is_not_empty(self):
    temp_pants_ini_path = self.create_file("pants.ini", contents="[GLOBAL]")
    with self.assertRaisesWithMessageContaining(TaskError, temp_pants_ini_path):
      self.execute_task()
