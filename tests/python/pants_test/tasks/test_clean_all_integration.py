# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import subprocess

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class CleanAllTest(PantsRunIntegrationTest):
  def test_clean_all_on_wrong_dir(self):
    with temporary_dir() as workdir:
      self.assert_failure(self.run_pants_with_workdir(["clean-all"], workdir))
      self.assert_failure(self.run_pants_with_workdir(["clean-all", "--async"], workdir))

  # Ensure async clean-all exits normally. 
  def test_clean_all_async(self):
    self.assert_success(self.run_pants(["clean-all", "--async"]))

  # The tests below check for the existence of trash directories.
  def test_empty_trash(self):
    with self.temporary_workdir() as work_dir:
      trash_dir = os.path.join(work_dir, "trash")
      subprocess.call(["touch", trash_dir + "foo.txt"])
      self.assert_success(self.run_pants_with_workdir(["clean-all"], work_dir))
      self.assertFalse(os._exists(trash_dir))

  def test_empty_trash_async(self):
    with self.temporary_workdir() as work_dir:
      trash_dir = os.path.join(work_dir, "trash")
      subprocess.call(["touch", trash_dir + "foo.txt"])
      self.assert_success(self.run_pants_with_workdir(["clean-all", "--async"], work_dir))
      self.assertFalse(os._exists(trash_dir))
