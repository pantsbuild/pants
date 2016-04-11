# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from xml.dom import minidom

from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class IdeaPluginIntegrationTest(PantsRunIntegrationTest):
  RESOURCE = 'java-resource'
  TEST_RESOURCE = 'java-test-resource'

  def _do_check(self, path, expected_properties):
    """Check to see that the project contains the expected source folders."""

    iws_file = os.path.join(path, 'project.iws')
    self.assertTrue(os.path.exists(iws_file))
    dom = minidom.parse(iws_file)

    self.assertEqual(1, len(dom.getElementsByTagName("project")))
    project = dom.getElementsByTagName("project")[0]

    self.assertEqual(1, len(project.getElementsByTagName('component')))
    component = project.getElementsByTagName('component')[0]

    actual_properties = component.getElementsByTagName('property')
    self.assertEqual(len(actual_properties), len(expected_properties))

    for i in range(len(expected_properties)):
      actual_property = actual_properties[i]
      expected_property = expected_properties[i]

      self.assertEqual(expected_property[0], actual_property.getAttribute('name'))
      for value in expected_property[1]:
        self.assertIn(value, actual_property.getAttribute('value'))

  def test_idea_plugin_single_target(self):
    with self.temporary_workdir() as workdir:
      target_a = 'examples/src/scala/org/pantsbuild/example/hello:hello'
      pants_run = self.run_pants_with_workdir(['idea-plugin', '--no-open', target_a], workdir)
      self.assert_success(pants_run)

      expected_properties = [("targets", [target_a]),
                             ("project_path", ["examples/src/scala/org/pantsbuild/example/hello"])]
      project_dir = os.path.join(pants_run.workdir, "idea-plugin/idea-plugin/PluginGen_idea_plugin/project")
      self._do_check(project_dir, expected_properties)

  def test_idea_plugin_single_directory(self):
    with self.temporary_workdir() as workdir:
      target_a = 'testprojects/src/python/antlr::'
      pants_run = self.run_pants_with_workdir(['idea-plugin', '--no-open', target_a], workdir)
      self.assert_success(pants_run)

      expected_properties = [("targets", [target_a]),
                             ("project_path", ["testprojects/src/python/antlr"])]
      project_dir = os.path.join(pants_run.workdir, "idea-plugin/idea-plugin/PluginGen_idea_plugin/project")
      self._do_check(project_dir, expected_properties)

  def test_idea_plugin_multiple_targets(self):
    with self.temporary_workdir() as workdir:
      target_a = 'examples/src/scala/org/pantsbuild/example/hello:'
      target_b = 'testprojects/src/python/antlr::'
      pants_run = self.run_pants_with_workdir(['idea-plugin', '--no-open', target_a, target_b], workdir)
      self.assert_success(pants_run)

      expected_properties = [("targets", [target_a]),
                             ("project_path", ["examples/src/scala/org/pantsbuild/example/hello"])]
      project_dir = os.path.join(pants_run.workdir, "idea-plugin/idea-plugin/PluginGen_idea_plugin/project")
      self._do_check(project_dir, expected_properties)
