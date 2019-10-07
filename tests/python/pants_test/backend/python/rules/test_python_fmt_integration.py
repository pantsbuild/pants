# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from os.path import relpath
from pathlib import Path

from pants.util.contextutil import temporary_file, temporary_file_path
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_daemon


class PythonFmtIntegrationTest(PantsRunIntegrationTest):
  def test_black_one_python_source_should_leave_one_file_unchanged(self):
    command = [
      'fmt-v2',
      'examples/src/python/example/hello/main:main'
      ]
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    self.assertNotIn("reformatted", pants_run.stderr_data)
    self.assertIn("1 file left unchanged", pants_run.stderr_data)


  def test_black_two_python_sources_should_leave_two_files_unchanged(self):
    command = [
      'fmt-v2',
      'examples/src/python/example/hello/greet:greet'
      ]
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    self.assertNotIn("reformatted", pants_run.stderr_data)
    self.assertIn("2 files left unchanged", pants_run.stderr_data)


  def test_black_should_pickup_default_config(self):
    # If the default config (pyproject.toml is picked up, the compilation_failure target will be skipped
    command = [
      'fmt-v2',
      'testprojects/src/python/unicode/compilation_failure::'
      ]
    pants_run = self.run_pants(command=command)
    self.assert_success(pants_run)
    self.assertNotIn("reformatted", pants_run.stderr_data)
    self.assertNotIn("unchanged", pants_run.stderr_data)
    self.assertIn("Nothing to do", pants_run.stderr_data)


  def test_black_should_pickup_non_default_config(self):
    # If a valid toml file without a black configuration section is picked up,
    # Black won't skip the compilation_failure and will fail
    with temporary_file_path(root_dir=".", suffix=".toml") as empty_config:
      command = [
        'fmt-v2',
        'testprojects/src/python/unicode/compilation_failure::',
        f'--black-config={relpath(empty_config)}'
        ]
      pants_run = self.run_pants(command=command)
    self.assert_failure(pants_run)
    self.assertNotIn("reformatted", pants_run.stderr_data)
    self.assertNotIn("unchanged", pants_run.stderr_data)
    self.assertIn("1 file failed to reformat", pants_run.stderr_data)


  def test_black_should_format_python_code(self):
    # Open file in the greet target as the BUILD file globs python files from there
    with temporary_file(root_dir="./examples/src/python/example/hello/greet/", suffix=".py") as code:
      file_name = code.name
      code.write(b"x     = 42")
      code.close()
      command = [
        'fmt-v2',
        'examples/src/python/example/hello/greet:greet'
        ]
      pants_run = self.run_pants(command=command)
      formatted = Path(file_name).read_text();
      self.assertEqual("x = 42\n", formatted)
    self.assert_success(pants_run)
    self.assertIn("1 file reformatted", pants_run.stderr_data)
    self.assertIn("2 files left unchanged", pants_run.stderr_data)
