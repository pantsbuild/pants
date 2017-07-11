# coding=utf-8
# Copyright 2016 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from textwrap import dedent

from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_engine


class DependeesIntegrationTest(PantsRunIntegrationTest):

  TARGET = 'examples/src/scala/org/pantsbuild/example/hello/welcome'

  def run_dependees(self, *dependees_options):
    args = ['-q', 'dependees', self.TARGET]
    args.extend(dependees_options)

    pants_run = self.run_pants(args)
    self.assert_success(pants_run)
    return pants_run.stdout_data.strip()

  @ensure_engine
  def test_dependees_basic(self):
    pants_stdout = self.run_dependees()
    self.assertEqual(
      {'examples/src/scala/org/pantsbuild/example:jvm-run-example-lib',
       'examples/src/scala/org/pantsbuild/example/hello/exe:exe',
       'examples/tests/scala/org/pantsbuild/example/hello/welcome:welcome'},
      set(pants_stdout.split())
    )

  @ensure_engine
  def test_dependees_transitive(self):
    pants_stdout = self.run_dependees('--dependees-transitive')
    self.assertEqual(
      {'examples/src/scala/org/pantsbuild/example:jvm-run-example-lib',
       'examples/src/scala/org/pantsbuild/example/hello:hello',
       'examples/src/scala/org/pantsbuild/example:jvm-run-example',
       'examples/src/scala/org/pantsbuild/example/hello/exe:exe',
       'examples/tests/scala/org/pantsbuild/example/hello/welcome:welcome'},
      set(pants_stdout.split())
    )

  @ensure_engine
  def test_dependees_closed(self):
    pants_stdout = self.run_dependees('--dependees-closed')
    self.assertEqual(
      {'examples/src/scala/org/pantsbuild/example/hello/welcome:welcome',
       'examples/src/scala/org/pantsbuild/example:jvm-run-example-lib',
       'examples/src/scala/org/pantsbuild/example/hello/exe:exe',
       'examples/tests/scala/org/pantsbuild/example/hello/welcome:welcome'},
      set(pants_stdout.split())
    )

  @ensure_engine
  def test_dependees_json(self):
    pants_stdout = self.run_dependees('--dependees-output-format=json')
    self.assertEqual(
      dedent("""
      {
          "examples/src/scala/org/pantsbuild/example/hello/welcome:welcome": [
              "examples/src/scala/org/pantsbuild/example/hello/exe:exe",
              "examples/src/scala/org/pantsbuild/example:jvm-run-example-lib",
              "examples/tests/scala/org/pantsbuild/example/hello/welcome:welcome"
          ]
      }""").lstrip('\n'),
      pants_stdout
    )
