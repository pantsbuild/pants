# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import json
import os
from textwrap import dedent

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest, ensure_engine


class TestOptionsIntegration(PantsRunIntegrationTest):

  @classmethod
  def hermetic(cls):
    return True

  @ensure_engine
  def test_options_works_at_all(self):
    self.assert_success(self.run_pants(['options']))

  @ensure_engine
  def test_options_scope(self):
    pants_run = self.run_pants(['options', '--no-colors', '--scope=options'])
    self.assert_success(pants_run)
    self.assertIn('options.scope = options', pants_run.stdout_data)
    self.assertIn('options.name = None', pants_run.stdout_data)
    self.assertNotIn('publish.jar.scm_push_attempts = ', pants_run.stdout_data)

    pants_run = self.run_pants(['options', '--no-colors', '--scope=publish.jar'])
    self.assert_success(pants_run)
    self.assertNotIn('options.colors = False', pants_run.stdout_data)
    self.assertNotIn('options.scope = options', pants_run.stdout_data)
    self.assertNotIn('options.name = None', pants_run.stdout_data)
    self.assertIn('publish.jar.scm_push_attempts = ', pants_run.stdout_data)

  @ensure_engine
  def test_valid_json(self):
    pants_run = self.run_pants(['options', '--output-format=json'])
    self.assert_success(pants_run)
    try:
      output_map = json.loads(pants_run.stdout_data)
      self.assertIn("time", output_map)
      self.assertEquals(output_map["time"]["source"], "HARDCODED")
      self.assertEquals(output_map["time"]["value"], "False")
    except ValueError:
      self.fail("Invalid JSON output")

  @ensure_engine
  def test_valid_json_with_history(self):
    pants_run = self.run_pants(['options', '--output-format=json', '--show-history'])
    self.assert_success(pants_run)
    try:
      output_map = json.loads(pants_run.stdout_data)
      self.assertIn("time", output_map)
      self.assertEquals(output_map["time"]["source"], "HARDCODED")
      self.assertEquals(output_map["time"]["value"], "False")
      self.assertEquals(output_map["time"]["history"], [])
      for _, val in output_map.items():
        self.assertIn("history", val)
    except ValueError:
      self.fail("Invalid JSON output")

  @ensure_engine
  def test_options_option(self):
    pants_run = self.run_pants(['options', '--no-colors', '--name=colors', '--no-skip-inherited'])
    self.assert_success(pants_run)
    self.assertIn('options.colors = ', pants_run.stdout_data)
    self.assertIn('unpack-jars.colors = ', pants_run.stdout_data)
    self.assertNotIn('options.scope = ', pants_run.stdout_data)

  @ensure_engine
  def test_options_only_overridden(self):
    pants_run = self.run_pants(['options', '--no-colors', '--only-overridden'])
    self.assert_success(pants_run)
    self.assertIn('options.only_overridden = True', pants_run.stdout_data)
    self.assertNotIn('options.scope =', pants_run.stdout_data)
    self.assertNotIn('from HARDCODED', pants_run.stdout_data)
    self.assertNotIn('from NONE', pants_run.stdout_data)

  @ensure_engine
  def test_options_rank(self):
    pants_run = self.run_pants(['options', '--no-colors', '--rank=FLAG'])
    self.assert_success(pants_run)
    self.assertIn('options.rank = ', pants_run.stdout_data)
    self.assertIn('(from FLAG)', pants_run.stdout_data)
    self.assertNotIn('(from CONFIG', pants_run.stdout_data)
    self.assertNotIn('(from HARDCODED', pants_run.stdout_data)
    self.assertNotIn('(from NONE', pants_run.stdout_data)

  @ensure_engine
  def test_options_show_history(self):
    pants_run = self.run_pants(['options', '--no-colors', '--only-overridden', '--show-history'])
    self.assert_success(pants_run)
    self.assertIn('options.only_overridden = True', pants_run.stdout_data)
    self.assertIn('overrode False (from HARDCODED', pants_run.stdout_data)

  @ensure_engine
  def test_from_config(self):
    with temporary_dir(root_dir=os.path.abspath('.')) as tempdir:
      config_path = os.path.relpath(os.path.join(tempdir, 'config.ini'))
      with open(config_path, 'w+') as f:
        f.write(dedent("""
          [options]
          colors: False
          scope: options
          only_overridden: True
          show_history: True
        """))
      pants_run = self.run_pants(['--config-override={}'.format(config_path), 'options'])
      self.assert_success(pants_run)
      self.assertIn('options.only_overridden = True', pants_run.stdout_data)
      self.assertIn('(from CONFIG in {})'.format(config_path), pants_run.stdout_data)

  @ensure_engine
  def test_options_deprecation_from_config(self):
    with temporary_dir(root_dir=os.path.abspath('.')) as tempdir:
      config_path = os.path.relpath(os.path.join(tempdir, 'config.ini'))
      with open(config_path, 'w+') as f:
        f.write(dedent("""
          [GLOBAL]
          verify_config: False
          pythonpath: [
              "%(buildroot)s/testprojects/src/python",
            ]

          backend_packages: [
              "plugins.dummy_options",
            ]

          [options]
          colors: False
        """))
      pants_run = self.run_pants(['--config-override={}'.format(config_path), 'options'])
      self.assert_success(pants_run)


      self.assertIn('dummy-options.normal_option', pants_run.stdout_data)
      self.assertIn('dummy-options.dummy_crufty_deprecated_but_still_functioning',
                    pants_run.stdout_data)
      self.assertNotIn('dummy-options.dummy_crufty_expired', pants_run.stdout_data)

  @ensure_engine
  def test_from_config_invalid_section(self):
    with temporary_dir(root_dir=os.path.abspath('.')) as tempdir:
      config_path = os.path.relpath(os.path.join(tempdir, 'config.ini'))
      with open(config_path, 'w+') as f:
        f.write(dedent("""
          [DEFAULT]
          some_crazy_thing: 123

          [invalid_scope]
          colors: False
          scope: options

          [another_invalid_scope]
          colors: False
          scope: options
        """))
      pants_run = self.run_pants(['--config-override={}'.format(config_path),
                                  'goals'])
      self.assert_failure(pants_run)
      self.assertIn('ERROR] Invalid scope [invalid_scope]', pants_run.stderr_data)
      self.assertIn('ERROR] Invalid scope [another_invalid_scope]', pants_run.stderr_data)

  @ensure_engine
  def test_from_config_invalid_option(self):
    with temporary_dir(root_dir=os.path.abspath('.')) as tempdir:
      config_path = os.path.relpath(os.path.join(tempdir, 'config.ini'))
      with open(config_path, 'w+') as f:
        f.write(dedent("""
          [DEFAULT]
          some_crazy_thing: 123

          [test.junit]
          fail_fast: True
          invalid_option: True
        """))
      pants_run = self.run_pants(['--config-override={}'.format(config_path),
                                  'goals'])
      self.assert_failure(pants_run)
      self.assertIn("ERROR] Invalid option 'invalid_option' under [test.junit]",
                    pants_run.stderr_data)

  @ensure_engine
  def test_from_config_invalid_global_option(self):
    """
    This test can be interpreted in two ways:
      1. An invalid global option `invalid_global` will be caught.
      2. Variable `invalid_global` is not allowed in [GLOBAL].
    """
    with temporary_dir(root_dir=os.path.abspath('.')) as tempdir:
      config_path = os.path.relpath(os.path.join(tempdir, 'config.ini'))
      with open(config_path, 'w+') as f:
        f.write(dedent("""
          [DEFAULT]
          some_crazy_thing: 123

          [GLOBAL]
          invalid_global: True
          another_invalid_global: False

          [test.junit]
          fail_fast: True
        """))
      pants_run = self.run_pants(['--config-override={}'.format(config_path),
                                  'goals'])
      self.assert_failure(pants_run)
      self.assertIn("ERROR] Invalid option 'invalid_global' under [GLOBAL]", pants_run.stderr_data)
      self.assertIn("ERROR] Invalid option 'another_invalid_global' under [GLOBAL]",
                    pants_run.stderr_data)

  @ensure_engine
  def test_invalid_command_line_option_and_invalid_config(self):
    """
    Make sure invalid command line error will be thrown and exits.
    """
    with temporary_dir(root_dir=os.path.abspath('.')) as tempdir:
      config_path = os.path.relpath(os.path.join(tempdir, 'config.ini'))
      with open(config_path, 'w+') as f:
        f.write(dedent("""
          [test.junit]
          bad_option: True

          [invalid_scope]
          abc: 123
        """))

      # Run with invalid config and invalid command line option.
      # Should error out with invalid command line option only.
      pants_run = self.run_pants(['--config-override={}'.format(config_path),
                                  '--test-junit-invalid=ALL',
                                  'goals'])
      self.assert_failure(pants_run)
      self.assertIn("Exception message: Unrecognized command line flags on scope 'test.junit': --invalid",
                    pants_run.stderr_data)

      # Run with invalid config only.
      # Should error out with `bad_option` and `invalid_scope` in config.
      pants_run = self.run_pants(['--config-override={}'.format(config_path),
                                  'goals'])
      self.assert_failure(pants_run)
      self.assertIn("ERROR] Invalid option 'bad_option' under [test.junit]", pants_run.stderr_data)
      self.assertIn("ERROR] Invalid scope [invalid_scope]", pants_run.stderr_data)

  @ensure_engine
  def test_command_line_option_unused_by_goals(self):
    self.assert_success(self.run_pants(['goals', '--bundle-jvm-archive=zip']))
    self.assert_failure(self.run_pants(['goals', '--jvm-invalid=zip']))

  @ensure_engine
  def test_skip_inherited(self):
    pants_run = self.run_pants([
      '--no-colors', '--no-jvm-platform-validate-colors', '--test-junit-colors',
      '--unpack-jars-colors', '--no-resolve-ivy-colors', '--imports-ivy-imports-colors',
      '--compile-colors', '--no-compile-zinc-colors',
      'options', '--skip-inherited', '--name=colors',
    ])
    self.assert_success(pants_run)
    lines = (s.split('(', 1)[0] for s in pants_run.stdout_data.split('\n') if '(' in s)
    lines = [s.strip() for s in lines]
    # This should be included because it has no super-scopes.
    self.assertIn('colors = False', lines)
    # These should be included because they differ from the super-scope value.
    self.assertIn('test.junit.colors = True', lines)
    self.assertIn('unpack-jars.colors = True', lines)
    self.assertIn('imports.ivy-imports.colors = True', lines)
    self.assertIn('compile.colors = True', lines)
    self.assertIn('compile.zinc.colors = False', lines)
    # These should be omitted because they have the same value as their super-scope.
    self.assertNotIn('jvm-platform-validate.colors = False', lines)
    self.assertNotIn('resolve.ivy.colors = False', lines)

  @ensure_engine
  def test_pants_ignore_option(self):
    with temporary_dir(root_dir=os.path.abspath('.')) as tempdir:
      config_path = os.path.relpath(os.path.join(tempdir, 'config.ini'))
      with open(config_path, 'w+') as f:
        f.write(dedent("""
          [GLOBAL]
          pants_ignore: +['some/random/dir']
        """))
      pants_run = self.run_pants(['--config-override={}'.format(config_path),
                                  '--no-colors',
                                  'options'])
      self.assert_success(pants_run)
      self.assertIn("pants_ignore = ['.*/', '/dist/', 'some/random/dir'] (from CONFIG)",
                    pants_run.stdout_data)

  @ensure_engine
  def test_pants_ignore_option_non_default_dist_dir(self):
    with temporary_dir(root_dir=os.path.abspath('.')) as tempdir:
      config_path = os.path.relpath(os.path.join(tempdir, 'config.ini'))
      with open(config_path, 'w+') as f:
        f.write(dedent("""
          [GLOBAL]
          pants_ignore: +['some/random/dir']
          pants_distdir: some/other/dist/dir
        """))
      pants_run = self.run_pants(['--config-override={}'.format(config_path),
                                  '--no-colors',
                                  'options'])
      self.assert_success(pants_run)
      self.assertIn("pants_ignore = ['.*/', '/some/other/dist/dir/', 'some/random/dir'] (from CONFIG)",
                    pants_run.stdout_data)
