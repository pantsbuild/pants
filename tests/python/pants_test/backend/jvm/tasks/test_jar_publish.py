# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import pytest
from mock import MagicMock, mock_open, patch

from pants.backend.jvm.tasks.jar_publish import JarPublish
from pants_test.base_test import BaseTest
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase


class JarPublishTest(NailgunTaskTestBase):
  """Tests for junit_run._JUnitRunner class"""

  options_scope = 'jar.publish'
  _jar_publish = None

  @classmethod
  def task_type(cls):
    return JarPublish

  def _create_context(self, properties=None, target_roots=None):
    return self.context(
      options={
        'jar.publish': {
          'jvm_options': ['-Dfoo=bar'],
          'repos': {
            'some_ext_repo': {
              'resolver': 'artifactory.foobar.com',
              'confs': ['default', 'sources'],
              'auth': '',
              'help': 'You break it, you bought it',
            }
          }
        }
      },
      target_roots=target_roots)

  def setUp(self):
    super(JarPublishTest, self).setUp()

    # Hack to make sure subsystems are initialized
    # self.context()
    JarPublish.options_scope = 'jar.publish'
#    with patch('JarPublish.options_scope', 'jar.publish'):
    self._jar_publish = JarPublish(self._create_context(), ".")


  def test_options_with_no_auth(self):
    self._jar_publish._jvm_options = ["jvm_opt_1", "jvm_opt_2"]
    repo = {}
    modified_opts = self._jar_publish._ivy_jvm_options(repo)
    self.assertEqual(modified_opts, ["jvm_opt_1", "jvm_opt_2"])

  def test_options_with_auth(self):
    self._jar_publish._jvm_options = ["jvm_opt_1", "jvm_opt_2"]
    repo = {
      'auth': 'blah',
      'username': 'mjk',
      'password': 'h.',
    }
    modified_opts = self._jar_publish._ivy_jvm_options(repo)
    self.assertEqual(modified_opts, ["jvm_opt_1", "jvm_opt_2", '-Dlogin=mjk', '-Dpassword=h.'])
    
    # Now run it again, and make sure we don't get dupes.
    modified_opts = self._jar_publish._ivy_jvm_options(repo)
    self.assertEqual(modified_opts, ["jvm_opt_1", "jvm_opt_2", '-Dlogin=mjk', '-Dpassword=h.'])
