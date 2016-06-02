# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


def ensure_experimental(test_fn):
  """Decorator for running once with and once without the --use-experimental-runner flag.

  """
  def wrapper(self, *args, **kwargs):
    JunitTestsConcurrencyIntegrationTest.USE_EXPERIMENTAL_RUNNER = True
    test_fn(self, *args, **kwargs)
    JunitTestsConcurrencyIntegrationTest.USE_EXPERIMENTAL_RUNNER = False
    test_fn(self, *args, **kwargs)
  return wrapper


class JunitTestsConcurrencyIntegrationTest(PantsRunIntegrationTest):
  """Run tests with different concurrency settings.

  Note that each of these tests is intended to be annotated with @ensure_experimental and run twice,
  once with the experimental runner enabled and once with it off.
  """
  USE_EXPERIMENTAL_RUNNER = False

  def run_pants_with_workdir(self, command, workdir, **kwargs):
    if self.USE_EXPERIMENTAL_RUNNER:
      command.append("--test-junit-use-experimental-runner")
    return super(JunitTestsConcurrencyIntegrationTest, self).run_pants_with_workdir(
      command, workdir, **kwargs)

  @ensure_experimental
  def test_parallel_target(self):
    """Checks the 'concurrency=parallel_classes' setting in the junit_tests() target"""
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
        'test',
        'testprojects/tests/java/org/pantsbuild/testproject/parallel'
      ], workdir)
      self.assert_success(pants_run)
      self.assertIn("OK (2 tests)", pants_run.stdout_data)

  @ensure_experimental
  def test_parallel_cmdline(self):
    """Checks the --test-junit-default-concurrency=PARALLEL_CLASSES option."""
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
        'test',
        '--test-junit-default-concurrency=PARALLEL_CLASSES',
        '--test-junit-parallel-threads=2',
        'testprojects/tests/java/org/pantsbuild/testproject/parallel:cmdline'
      ], workdir)
      self.assert_success(pants_run)
      self.assertIn("OK (2 tests)", pants_run.stdout_data)

  # TODO(zundel): remove this test when --default-parallel is removed
  @ensure_experimental
  def test_parallel_cmdline_deprecated_arg(self):
    """Checks the --test-junit-default-parallel option still works."""
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
        'test',
        '--test-junit-default-parallel',
        '--test-junit-parallel-threads=2',
        'testprojects/tests/java/org/pantsbuild/testproject/parallel:cmdline'
      ], workdir)
      self.assert_success(pants_run)
      self.assertIn("OK (2 tests)", pants_run.stdout_data)

  @ensure_experimental
  def test_concurrency_serial_default(self):
    """Checks the --test-junit-default-concurrency=SERIAL option."""
    with self.temporary_workdir() as workdir:
      # NB(zundel): the timeout for each test in ParallelMethodsDefaultParallel tests is
      # currently set to 3 seconds making this test take about 2 seconds to run due
      # to (1 timeout failure)
      pants_run = self.run_pants_with_workdir([
        'test',
        '--test-junit-default-concurrency=SERIAL',
        '--test-junit-parallel-threads=2',
        'testprojects/tests/java/org/pantsbuild/testproject/parallel:cmdline'
      ], workdir)
      self.assert_failure(pants_run)
      # Its not deterministic which test will fail, but one of them should timeout
      self.assertIn("Tests run: 2,  Failures: 1", pants_run.stdout_data)

  @ensure_experimental
  def test_parallel_annotated_test_parallel(self):
    """Checks the @TestParallel annotation."""
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
        'test',
        '--test-junit-default-concurrency=SERIAL',
        'testprojects/tests/java/org/pantsbuild/testproject/parallel:annotated-parallel'
      ], workdir)
      self.assert_success(pants_run)
      self.assertIn("OK (2 tests)", pants_run.stdout_data)

  @ensure_experimental
  def test_parallel_annotated_test_serial(self):
    """Checks the @TestSerial annotation."""
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
        'test',
        '--test-junit-default-concurrency=PARALLEL_CLASSES',
        '--test-junit-parallel-threads=2',
        'testprojects/tests/java/org/pantsbuild/testproject/parallel:annotated-serial'
      ], workdir)
      self.assert_success(pants_run)
      self.assertIn("OK (2 tests)", pants_run.stdout_data)

  @ensure_experimental
  def test_parallel_both(self):
    """Checks the concurency='parallel_both' setting."""
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
        'test',
        '--test-junit-default-concurrency=SERIAL',
        '--test-junit-parallel-threads=4',
        'testprojects/tests/java/org/pantsbuild/testproject/parallelclassesandmethods'
      ], workdir)
      self.assert_success(pants_run)
      self.assertIn("OK (4 tests)", pants_run.stdout_data)

  @ensure_experimental
  def test_parallel_both_cmdline(self):
    """Checks the --test-junit-default_concurrency=PARALLEL_CLASSES_AND_METHODS setting."""
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
         'test',
        '--test-junit-default-concurrency=PARALLEL_CLASSES_AND_METHODS',
        '--test-junit-parallel-threads=4',
        'testprojects/tests/java/org/pantsbuild/testproject/parallelclassesandmethods:cmdline'
        ], workdir)
      self.assert_success(pants_run)
      self.assertIn("OK (4 tests)", pants_run.stdout_data)

  @ensure_experimental
  def test_parallel_both_serial_default(self):
    """Checks the --test-junit-default-concurrency=SERIAL setting."""
    with self.temporary_workdir() as workdir:
      # NB(zundel): the timeout for each test in ParallelMethodsDefaultParallel tests is
      # currently set to 1 seconds making this test take about 3 seconds to run due
      # to (3 timeout failures)
      pants_run = self.run_pants_with_workdir([
         'test',
        '--test-junit-default-concurrency=SERIAL',
        '--test-junit-parallel-threads=4',
        'testprojects/tests/java/org/pantsbuild/testproject/parallelclassesandmethods:cmdline'
        ], workdir)
      self.assert_failure(pants_run)
      # Its not deterministic which test will fail, but 3/4 of them should timeout
      self.assertIn("Tests run: 4,  Failures: 3", pants_run.stdout_data)


class ExperimentalOnlyJunitTestsConcurrencyIntegrationTest(PantsRunIntegrationTest):
  """The following tests only work with the experimental runner."""

  def test_concurrency_annotated_test_serial_parallel_both(self):
    """Checks the @TestSerial annotation with --test-junit-default-concurrency=PARALLEL_CLASSES_AND_METHODS."""
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
        'test',
        '--test-junit-default-concurrency=PARALLEL_CLASSES_AND_METHODS',
        '--test-junit-parallel-threads=2',
        '--test-junit-use-experimental-runner',
        'testprojects/tests/java/org/pantsbuild/testproject/parallel:annotated-serial'
      ], workdir)
      self.assert_success(pants_run)
      self.assertIn("OK (2 tests)", pants_run.stdout_data)

  def test_parallel_methods(self):
    """Checks the concurency='parallel_methods' setting."""
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
        'test',
        '--test-junit-default-concurrency=SERIAL',
        '--test-junit-parallel-threads=4',
        '--test-junit-use-experimental-runner',
        'testprojects/tests/java/org/pantsbuild/testproject/parallelmethods'
      ], workdir)
      self.assert_success(pants_run)
      self.assertIn("OK (4 tests)", pants_run.stdout_data)

  def test_parallel_methods_cmdline(self):
    """Checks the --test-junit-default_concurrency=PARALLEL_METHODS setting."""
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir([
        'test',
        '--test-junit-default-concurrency=PARALLEL_METHODS',
        '--test-junit-parallel-threads=4',
        '--test-junit-use-experimental-runner',
        'testprojects/tests/java/org/pantsbuild/testproject/parallelmethods:cmdline'
      ], workdir)
      self.assert_success(pants_run)
      self.assertIn("OK (4 tests)", pants_run.stdout_data)
