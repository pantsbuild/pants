# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
from xml.dom import minidom

from pants.base.build_environment import get_buildroot
from pants.util.contextutil import temporary_file
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class IdeaPluginIntegrationTest(PantsRunIntegrationTest):
  RESOURCE = 'java-resource'
  TEST_RESOURCE = 'java-test-resource'

  def _do_check(self, project_dir_path, expected_project_path, expected_targets):
    """Check to see that the project contains the expected source folders."""

    iws_file = os.path.join(project_dir_path, 'project.iws')
    self.assertTrue(os.path.exists(iws_file))
    dom = minidom.parse(iws_file)
    self.assertEqual(1, len(dom.getElementsByTagName("project")))
    project = dom.getElementsByTagName("project")[0]

    self.assertEqual(1, len(project.getElementsByTagName('component')))
    component = project.getElementsByTagName('component')[0]

    actual_properties = component.getElementsByTagName('property')
    # 3 properties: targets, project_path, pants_idea_plugin_version
    self.assertEqual(3, len(actual_properties))

    self.assertEqual('targets', actual_properties[0].getAttribute('name'))
    actual_targets = json.loads(actual_properties[0].getAttribute('value'))
    abs_expected_target_specs = [os.path.join(get_buildroot(), relative_spec) for relative_spec in expected_targets]
    self.assertEqual(abs_expected_target_specs, actual_targets)

    self.assertEqual('project_path', actual_properties[1].getAttribute('name'))
    actual_project_path = actual_properties[1].getAttribute('value')
    self.assertEqual(os.path.join(get_buildroot(), expected_project_path), actual_project_path)

    self.assertEqual('pants_idea_plugin_version', actual_properties[2].getAttribute('name'))
    self.assertEqual('0.0.1', actual_properties[2].getAttribute('value'))

  def _get_project_dir(self, output_file):
    with open(output_file, 'r') as result:
      return result.readlines()[0]

  def _run_and_check(self, project_path, targets):
    with self.temporary_workdir() as workdir:
      with temporary_file(root_dir=workdir, cleanup=True) as output_file:
        pants_run = self.run_pants_with_workdir(
          ['idea-plugin', '--output-file={}'.format(output_file.name), '--no-open'] + targets, workdir)
        self.assert_success(pants_run)

        project_dir = self._get_project_dir(output_file.name)
        self.assertTrue(os.path.exists(project_dir), "{} does not exist".format(project_dir))
        self._do_check(project_dir, project_path, targets)

  def test_idea_plugin_single_target(self):

    target = 'examples/src/scala/org/pantsbuild/example/hello:hello'
    project_path = "examples/src/scala/org/pantsbuild/example/hello"

    self._run_and_check(project_path, [target])

  def test_idea_plugin_single_directory(self):
    target = 'testprojects/src/python/antlr::'
    project_path = "testprojects/src/python/antlr"

    self._run_and_check(project_path, [target])

  def test_idea_plugin_multiple_targets(self):
    target_a = 'examples/src/scala/org/pantsbuild/example/hello:'
    target_b = 'testprojects/src/python/antlr::'

    # project_path is always the directory of the first target,
    # which is where intellij is going to zoom in at project view.
    project_path = 'examples/src/scala/org/pantsbuild/example/hello'

    self._run_and_check(project_path, [target_a, target_b])
