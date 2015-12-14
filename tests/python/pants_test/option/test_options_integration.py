# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from textwrap import dedent

from pants.util.contextutil import temporary_dir
from pants_test.pants_run_integration_test import PantsRunIntegrationTest


class TestOptionsIntegration(PantsRunIntegrationTest):

  def test_options_works_at_all(self):
    self.assert_success(self.run_pants(['options']))

  def test_options_scope(self):
    pants_run = self.run_pants(['options', '--no-colors', '--scope=options'])
    self.assert_success(pants_run)
    self.assertIn('options.colors = False', pants_run.stdout_data)
    self.assertIn('options.scope = options', pants_run.stdout_data)
    self.assertIn('options.name = None', pants_run.stdout_data)
    self.assertNotIn('publish.jar.scm_push_attempts = ', pants_run.stdout_data)

    pants_run = self.run_pants(['options', '--no-colors', '--scope=publish.jar'])
    self.assert_success(pants_run)
    self.assertNotIn('options.colors = False', pants_run.stdout_data)
    self.assertNotIn('options.scope = options', pants_run.stdout_data)
    self.assertNotIn('options.name = None', pants_run.stdout_data)
    self.assertIn('publish.jar.scm_push_attempts = ', pants_run.stdout_data)

  def test_options_option(self):
    pants_run = self.run_pants(['options', '--no-colors', '--name=colors'])
    self.assert_success(pants_run)
    self.assertIn('options.colors = ', pants_run.stdout_data)
    self.assertIn('unpack-jars.colors = ', pants_run.stdout_data)
    self.assertNotIn('options.scope = ', pants_run.stdout_data)

  def test_options_only_overridden(self):
    pants_run = self.run_pants(['options', '--no-colors', '--only-overridden'])
    self.assert_success(pants_run)
    self.assertIn('options.only_overridden = True', pants_run.stdout_data)
    self.assertIn('options.colors = False', pants_run.stdout_data)
    self.assertNotIn('options.scope =', pants_run.stdout_data)
    self.assertNotIn('from HARDCODED', pants_run.stdout_data)
    self.assertNotIn('from NONE', pants_run.stdout_data)

  def test_options_rank(self):
    pants_run = self.run_pants(['options', '--no-colors', '--rank=FLAG'])
    self.assert_success(pants_run)
    self.assertIn('options.rank = ', pants_run.stdout_data)
    self.assertIn('(from FLAG)', pants_run.stdout_data)
    self.assertNotIn('(from CONFIG', pants_run.stdout_data)
    self.assertNotIn('(from HARDCODED', pants_run.stdout_data)
    self.assertNotIn('(from NONE', pants_run.stdout_data)

  def test_options_show_history(self):
    pants_run = self.run_pants(['options', '--no-colors', '--only-overridden', '--show-history'])
    self.assert_success(pants_run)
    self.assertIn('options.only_overridden = True', pants_run.stdout_data)
    self.assertIn('overrode False (from HARDCODED', pants_run.stdout_data)

  def test_from_config(self):
    with temporary_dir(root_dir=os.path.abspath('.')) as tempdir:
      config_path = os.path.relpath(os.path.join(tempdir, 'config.ini'))
      with open(config_path, 'w+') as f:
        f.write(dedent('''
          [options]
          colors: False
          scope: options
          only_overridden: True
          show_history: True
        '''))
      pants_run = self.run_pants(['--config-override={}'.format(config_path), 'options'])
      self.assert_success(pants_run)
      self.assertIn('options.only_overridden = True', pants_run.stdout_data)
      self.assertIn('(from CONFIG in {})'.format(config_path), pants_run.stdout_data)
