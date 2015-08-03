# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.jvm.tasks.jar_publish import JarPublish
from pants_test.jvm.nailgun_task_test_base import NailgunTaskTestBase


class JarPublishTest(NailgunTaskTestBase):
  """Tests for backend jvm JarPublish class"""

  DEFAULT_JVM_OPTS = ["jvm_opt_1", "jvm_opt_2"]

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

    JarPublish.options_scope = 'jar.publish'
    self._jar_publish = JarPublish(self._create_context(), ".")

  def test_options_with_no_auth(self):
    self._jar_publish._jvm_options = self.DEFAULT_JVM_OPTS
    repo = {}
    modified_opts = self._jar_publish._ivy_jvm_options(repo)
    self.assertEqual(modified_opts, self.DEFAULT_JVM_OPTS)

  def test_options_with_auth(self):
    self._jar_publish._jvm_options = self.DEFAULT_JVM_OPTS

    username = 'mjk'
    password = 'h.'
    creds_options = ['-Dlogin={}'.format(username), '-Dpassword={}'.format(password)]

    repo = {
      'auth': 'blah',
      'username': username,
      'password': password,
    }
    modified_opts = self._jar_publish._ivy_jvm_options(repo)
    self.assertEqual(modified_opts, self.DEFAULT_JVM_OPTS + creds_options)

    # Now run it again, and make sure we don't get dupes.
    modified_opts = self._jar_publish._ivy_jvm_options(repo)
    self.assertEqual(modified_opts, self.DEFAULT_JVM_OPTS + creds_options)
