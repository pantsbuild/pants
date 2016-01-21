# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestPantsDaemonIntegration(PantsRunIntegrationTest):
  def test_pantsd_run(self):
    pantsd_config = {'DEFAULT': {'enable_pantsd': True}}

    with self.temporary_workdir() as workdir:
      # Explicitly kill any running pantsd instances for the current buildroot.
      self.assert_success(
        self.run_pants_with_workdir(['kill-pantsd'], workdir)
      )

      # Start pantsd implicitly via a throwaway invocation.
      self.assert_success(
        self.run_pants_with_workdir(['help'], workdir, pantsd_config)
      )

      # This run should execute via pantsd testing the end to end client/server.
      self.assert_success(
        self.run_pants_with_workdir(['help-advanced'], workdir, pantsd_config)
      )

      # This tests a deeper pantsd-based run by actually invoking a full compile.
      self.assert_success(
        self.run_pants_with_workdir(
          ['compile', 'examples/src/scala/org/pantsbuild/example/hello/welcome'],
          workdir,
          pantsd_config)
      )

      # Explicitly kill pantsd (from a pantsd-launched runner).
      self.assert_success(
        self.run_pants_with_workdir(['kill-pantsd'], workdir, pantsd_config)
      )
