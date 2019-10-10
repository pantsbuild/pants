# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from os.path import relpath
from pathlib import Path

from pants.util.contextutil import temporary_dir, temporary_file, temporary_file_path
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


  def test_grey_should_pickup_non_default_config(self):
    # If a valid toml file without a black configuration section is picked up,
    # Black won't skip the compilation_failure and will fail
    with temporary_file_path(root_dir=".", suffix=".toml") as empty_config:
      command = [
        'fmt-v2',
        'testprojects/src/python/unicode/compilation_failure::',
        '--python_fmt-tool=black_with_two_spaces_indent',
        f'--black_with_two_spaces_indent-config={relpath(empty_config)}'
        ]
      pants_run = self.run_pants(command=command)
    self.assert_failure(pants_run)
    self.assertNotIn("reformatted", pants_run.stderr_data)
    self.assertNotIn("unchanged", pants_run.stderr_data)
    self.assertIn("1 file failed to reformat", pants_run.stderr_data)


  def test_black_should_format_python_code_with_4_spaces_indent(self):
    # Open file in the greet target as the BUILD file globs python files from there
    with temporary_dir(root_dir=".") as root_dir:
      code = Path(root_dir, "code.py")
      code.touch()
      code.write_text("def hello():x=42")
      build = Path(root_dir, "BUILD")
      build.touch()
      build.write_text("python_library()")
      command = [
        'fmt-v2',
        f'{root_dir}:'
        ]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      formatted = Path(code).read_text();
      self.assertEqual("def hello():\n    x = 42\n", formatted)
    self.assertIn("1 file reformatted", pants_run.stderr_data)
    self.assertNotIn("unchanged", pants_run.stderr_data)
    self.assertNotIn("failed", pants_run.stderr_data)


  def test_grey_should_format_python_code_with_2_spaces_indent(self):
    # Open file in the greet target as the BUILD file globs python files from there
    with temporary_dir(root_dir=".") as root_dir:
      code = Path(root_dir, "code.py")
      code.touch()
      code.write_text("def hello():x=42")
      build = Path(root_dir, "BUILD")
      build.touch()
      build.write_text("python_library()")
      command = [
        'fmt-v2',
        '--python_fmt-tool=black_with_two_spaces_indent',
        f'{root_dir}:'
        ]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      formatted = Path(code).read_text();
      self.assertEqual("def hello():\n  x = 42\n", formatted)
    self.assertIn("1 file reformatted", pants_run.stderr_data)
    self.assertNotIn("unchanged", pants_run.stderr_data)
    self.assertNotIn("failed", pants_run.stderr_data)
