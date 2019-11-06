# Copyright 2019 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import os
from contextlib import contextmanager
from os.path import relpath
from pathlib import Path

from pants.testutil.pants_run_integration_test import PantsRunIntegrationTest
from pants.util.contextutil import temporary_dir, temporary_file_path
from pants.util.dirutil import safe_file_dump


def write_build_file(root_dir):
  safe_file_dump(os.path.join(root_dir, "BUILD"), "python_library()")

INCONSISTENTLY_FORMATTED_HELLO: str = "def hello():x=42"
CONSISTENTLY_FORMATTED_HELLO: str = "def hello():\n    x = 42\n"


def write_inconsistently_formatted_file(root_dir, filename) -> Path:
  filepath = os.path.join(root_dir, filename)
  safe_file_dump(filepath, INCONSISTENTLY_FORMATTED_HELLO)
  return Path(filepath)


def write_consistently_formatted_file(root_dir, filename) -> Path:
  filepath = os.path.join(root_dir, filename)
  safe_file_dump(filepath, CONSISTENTLY_FORMATTED_HELLO)
  return Path(filepath)


@contextmanager
def build_directory():
  with temporary_dir(root_dir=".") as root_dir:
    write_build_file(root_dir)
    yield root_dir


class PythonFmtIntegrationTest(PantsRunIntegrationTest):
  def test_black_one_python_source_should_leave_one_file_unchanged(self):
    with build_directory() as root_dir:
      code = write_consistently_formatted_file(root_dir, "hello.py")
      command = [
        'fmt-v2',
        f'{root_dir}'
      ]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      after_formatting = code.read_text()
      self.assertEqual(CONSISTENTLY_FORMATTED_HELLO, after_formatting)
    self.assertNotIn("reformatted", pants_run.stderr_data)
    self.assertIn("1 file left unchanged", pants_run.stderr_data)

  def test_black_lint_given_formatted_file(self):
    with build_directory() as root_dir:
      code = write_consistently_formatted_file(root_dir, "hello.py")
      command = [
        'lint-v2',
        f'{root_dir}'
      ]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      after_formatting = code.read_text()
      self.assertEqual(CONSISTENTLY_FORMATTED_HELLO, after_formatting)
    self.assertNotIn("reformatted", pants_run.stderr_data)
    self.assertIn("1 file would be left unchanged", pants_run.stderr_data)

  def test_black_two_python_sources_should_leave_two_files_unchanged(self):
    with build_directory() as root_dir:
      foo = write_consistently_formatted_file(root_dir, "foo.py")
      bar = write_consistently_formatted_file(root_dir, "bar.py")
      command = [
        'fmt-v2',
        f'{root_dir}'
      ]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      foo_after_formatting = foo.read_text()
      self.assertEqual(CONSISTENTLY_FORMATTED_HELLO, foo_after_formatting)
      bar_after_formatting = bar.read_text()
      self.assertEqual(CONSISTENTLY_FORMATTED_HELLO, bar_after_formatting)
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
    with build_directory() as root_dir:
      code = write_inconsistently_formatted_file(root_dir, "hello.py")
      command = [
        'fmt-v2',
        f'{root_dir}'
      ]
      pants_run = self.run_pants(command=command)
      self.assert_success(pants_run)
      after_formatting = code.read_text()
      self.assertEqual(CONSISTENTLY_FORMATTED_HELLO, after_formatting)
    self.assertIn("1 file reformatted", pants_run.stderr_data)
    self.assertNotIn("unchanged", pants_run.stderr_data)

  def test_black_lint_should_fail_but_not_format_python_code(self):
    with build_directory() as root_dir:
      code = write_inconsistently_formatted_file(root_dir, "hello.py")
      command = [
        'lint-v2',
        f'{root_dir}'
      ]
      pants_run = self.run_pants(command=command)
      self.assert_failure(pants_run)
      after_formatting = code.read_text()
      self.assertEqual(INCONSISTENTLY_FORMATTED_HELLO, after_formatting)
    self.assertIn("1 file would be reformatted", pants_run.stderr_data)
    self.assertNotIn("1 file reformatted", pants_run.stderr_data)
    self.assertNotIn("unchanged", pants_run.stderr_data)

  def test_black_lint_given_multiple_files(self):
    with build_directory() as root_dir:
      write_inconsistently_formatted_file(root_dir, "incorrect.py")
      write_inconsistently_formatted_file(root_dir, "broken.py")
      write_consistently_formatted_file(root_dir, "pristine.py")
      command = [
        'lint-v2',
        f'{root_dir}'
      ]
      pants_run = self.run_pants(command=command)
      self.assert_failure(pants_run)
    self.assertIn("2 files would be reformatted", pants_run.stderr_data)
    self.assertNotIn("2 files reformatted", pants_run.stderr_data)
    self.assertIn("1 file would be left unchanged", pants_run.stderr_data)
    self.assertNotIn("1 file left unchanged", pants_run.stderr_data)

  def test_black_lint_given_multiple_targets(self):
    with build_directory() as a_dir:
      with build_directory() as another_dir:
        write_inconsistently_formatted_file(a_dir, "incorrect.py")
        write_inconsistently_formatted_file(another_dir, "broken.py")
        write_inconsistently_formatted_file(another_dir, "messed_up.py")
        command = [
          'lint-v2',
          f'{a_dir}',
          f'{another_dir}'
        ]
        pants_run = self.run_pants(command=command)
        self.assert_failure(pants_run)
    self.assertIn("1 file would be reformatted", pants_run.stderr_data)
    self.assertIn("2 files would be reformatted", pants_run.stderr_data)
    self.assertNotIn("unchanged", pants_run.stderr_data)
