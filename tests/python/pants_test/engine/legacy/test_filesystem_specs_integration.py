# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os.path

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.dirutil import rm_rf, touch


class FilesystemSpecsIntegrationTest(PantsRunIntegrationTest):

  def test_valid_file(self) -> None:
    pants_run = self.run_pants(["list", "testprojects/tests/python/pants/dummies/test_pass.py"])
    self.assert_success(pants_run)
    assert {
      'testprojects/tests/python/pants:dummies_directory',
      'testprojects/tests/python/pants/dummies:passing_target',
      'testprojects/tests/python/pants:secondary_source_file_owner',
    } == set(pants_run.stdout_data.splitlines())

  def test_nonexistent_file(self) -> None:
    pants_run = self.run_pants(["list", "src/fake.py"])
    self.assert_failure(pants_run)
    assert (
      'Unmatched glob from file arguments: "src/fake.py"'
      in pants_run.stderr_data
    )

  def test_no_owner(self) -> None:
    no_owning_file = 'testprojects/tests/python/pants/nonexistent/test_nonexistent.py'
    touch(no_owning_file)
    try:
      pants_run = self.run_pants(['list', no_owning_file])
      assert 'WARNING: No targets were matched in' in pants_run.stderr_data
    finally:
      rm_rf(os.path.dirname(no_owning_file))
