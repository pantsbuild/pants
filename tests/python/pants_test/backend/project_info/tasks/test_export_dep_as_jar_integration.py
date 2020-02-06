# Copyright 2020 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

import json
import re

from pants_test.backend.jvm.tasks.jvm_compile.scala.base_scalac_plugin_integration_test import (
  ScalacPluginIntegrationTestBase,
)


class ExportDepAsJarIntegrationTest(ScalacPluginIntegrationTestBase):

  scalac_test_targets_dir = 'examples/src/scala/org/pantsbuild/example/scalac'
  javac_test_targets_dir = 'examples/src/java/org/pantsbuild/example/javac'
  commonly_expected_options = {
    'scalac_args':  ['-encoding', 'UTF-8', '-g:vars', '-target:jvm-1.8', '-deprecation', '-unchecked', '-feature'],
    'javac_args': ['-encoding', 'UTF-8', '-source', '1.8', '-target', '1.8'],
    'extra_jvm_options': [],
  }

  def _do_test_compiler_options_in_export_output(self, config, target):
    with self.temporary_workdir() as workdir:
      pants_run = self.run_pants_with_workdir(
        ['export-dep-as-jar', target], workdir, config)
    self.assert_success(pants_run)
    export_result = json.loads(pants_run.stdout_data)
    return export_result

  def _check_compiler_options_for_target_are(self, target, expected_options_patterns, config):
    """
    Export the target, and check that the options are correct.
    """

    export_output = self._do_test_compiler_options_in_export_output(config, target)

    target_info = export_output['targets'][target]

    for (key, expeced_option_values) in expected_options_patterns.items():
      result_options = target_info[key]
      strigified_result_options = ' '.join(result_options)

      expeced_option_values += self.commonly_expected_options[key]

      assert len(expeced_option_values) == len(result_options)
      for pattern in expeced_option_values:
        assert (pattern in result_options) or \
               re.match(pattern, strigified_result_options)

  def test_compile_with_compiler_options(self):
    target_to_test = f'{self.scalac_test_targets_dir}/compiler_options:with_nonfatal_warnings'
    config = {
      'compile.rsc': {
        'compiler_option_sets_enabled_args': {
          'non_fatal_warnings': [
            '-S-Ywarn-unused'
          ]
        }
      }
    }
    expected_options = {'scalac_args': ['-Ywarn-unused']}
    self._check_compiler_options_for_target_are(target_to_test, expected_options, config)

  def test_global_compiler_plugin_with_global_options(self):
    target_to_test = f'{self.scalac_test_targets_dir}/plugin:global'
    config = self.with_global_plugin_args(
              ['arg1', 'arg2'],
              self.with_global_plugin_enabled()
            )
    expected_options = {'scalac_args': [
      r'\-Xplugin\:.*examples.src.scala.org.pantsbuild.example.scalac.plugin.simple_scalac_plugin/current/zinc/classes.*',
      '-P:simple_scalac_plugin:arg1',
      '-P:simple_scalac_plugin:arg2',
    ]}
    self._check_compiler_options_for_target_are(target_to_test, expected_options, config)

  def test_global_compiler_plugin_with_compiler_option_sets(self):
    target_to_test = f'{self.scalac_test_targets_dir}/plugin:global'
    config = self.with_compiler_option_sets_enabled_scalac_plugins()
    expected_options = {'scalac_args': [
      r'\-Xplugin\:.*examples.src.scala.org.pantsbuild.example.scalac.plugin.simple_scalac_plugin/current/zinc/classes.*',
      '-P:simple_scalac_plugin:abc',
      '-P:simple_scalac_plugin:def',
    ]}
    self._check_compiler_options_for_target_are(target_to_test, expected_options, config)

  def test_global_compiler_plugin_with_local_options(self):
    target_to_test = f'{self.scalac_test_targets_dir}/plugin:global_with_local_args'
    config = self.with_global_plugin_enabled()

    expected_options = {'scalac_args': [
      r'\-Xplugin\:.*examples.src.scala.org.pantsbuild.example.scalac.plugin.simple_scalac_plugin/current/zinc/classes.*',
      '-P:simple_scalac_plugin:args',
      '-P:simple_scalac_plugin:from',
      '-P:simple_scalac_plugin:target',
      '-P:simple_scalac_plugin:global_with_local_args',
    ]}
    self._check_compiler_options_for_target_are(target_to_test, expected_options, config)

  def test_local_compiler_plugin_with_local_options(self):
    target_to_test = f'{self.scalac_test_targets_dir}/plugin:local'
    config = {}
    expected_options = {'scalac_args': [
      r'\-Xplugin\:.*examples.src.scala.org.pantsbuild.example.scalac.plugin.simple_scalac_plugin/current/zinc/classes.*',
      '-P:simple_scalac_plugin:args',
      '-P:simple_scalac_plugin:from',
      '-P:simple_scalac_plugin:target',
      '-P:simple_scalac_plugin:local',
    ]}
    self._check_compiler_options_for_target_are(target_to_test, expected_options, config)

  def test_javac_options(self):
    target_to_test = f'{self.javac_test_targets_dir}/plugin:local'
    config = {}
    expected_options = {'javac_args': [
      '-Xplugin:simple_javac_plugin args from target local',
    ]}
    self._check_compiler_options_for_target_are(target_to_test, expected_options, config)

  def test_extra_jvm_options(self):
    target_to_test = f'testprojects/src/java/org/pantsbuild/testproject/extra_jvm_options:opts'
    config = {}
    expected_options = {'extra_jvm_options': ['-Dproperty.color=orange', '-Dproperty.size=2', '-DMyFlag', '-Xmx1m']}
    self._check_compiler_options_for_target_are(target_to_test, expected_options, config)
