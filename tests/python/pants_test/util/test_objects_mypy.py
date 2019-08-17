# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestObjectsWithMypy(PantsRunIntegrationTest):

  def run_mypy(self, tag, targets, **kwargs):
    return self.do_command(
      '--backend-packages=pants.contrib.mypy',
      f'--tag={tag}',
      'lint.mypy',
      '--verbose',
      '--config-file=build-support/mypy/mypy.ini',
      f'--whitelist-tag-name={tag}',
      *targets,
      **kwargs)

  def test_mypy_with_dataclasses(self):
    self.run_mypy(
      tag='extra_type_checked',
      targets=['testprojects/src/python/mypy:mypy-passing-examples'],
      success=True)

    pants_run = self.run_mypy(
      tag='extra_type_checked',
      targets=['testprojects/src/python/mypy:mypy-failing-examples'],
      success=False)

    # Validate that the correct error occurs, and that it's in the right location. We only need one
    # such test to ensure the location is correct, so including the precise file:line shouldn't be
    # too brittle.
    self.assertIn(
      'testprojects/src/python/mypy/dataclasses_mypy_failure.py:15:5: error: Argument 1 to "DC" has incompatible type "str"; expected "int"',
      pants_run.stdout_data)
