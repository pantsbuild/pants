# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import textwrap

from pants.backend.android.tasks.sign_apk import SignApkTask
from pants.base.exceptions import TaskError
from pants.util.contextutil import temporary_dir
from pants_test.android.test_android_base import TestAndroidBase


class SignApkTest(TestAndroidBase):
  """Test the package signing methods in pants.backend.android.tasks.SignApk"""

  _TEST_KEYSTORE = '%(homedir)s/.doesnt/matter/keystore_config.ini'

  @classmethod
  def task_type(cls):
    return SignApkTask

  @classmethod
  def _get_config(cls,
                  section=SignApkTask._CONFIG_SECTION,
                  option='keystore_config_location',
                  location=_TEST_KEYSTORE):
    ini = textwrap.dedent("""
    [{0}]

    {1}: {2}
    """).format(section, option, location)
    return ini

  class FakeKeystore(object):
    # Mock keystore to test the render_args method.
    def __init__(self):
      self.build_type = 'debug'
      self.keystore_name = 'key_name'
      self.keystore_location = '/path/to/key'
      self.keystore_alias = 'key_alias'
      self.keystore_password = 'keystore_password'
      self.key_password = 'key_password'

  class FakeDistribution(object):
    # Mock JDK distribution to test the render_args method.
    @classmethod
    def binary(cls, tool):
      return 'path/to/{0}'.format(tool)

  def test_sign_apk_smoke(self):
    task = self.prepare_task(config=self._get_config(),
                             build_graph=self.build_graph,
                             build_file_parser=self.build_file_parser)
    task.execute()

  def test_config_file(self):
    task = self.prepare_task(config=self._get_config(),
                             build_graph=self.build_graph,
                             build_file_parser=self.build_file_parser)
    task.config_file

  def test_no_config_file_defined(self):
    with self.assertRaises(TaskError):
      task = self.prepare_task(config=self._get_config(location=""),
                               build_graph=self.build_graph,
                               build_file_parser=self.build_file_parser)
      task.config_file

  def test_config_file_from_pantsini(self):
    with temporary_dir() as temp:
      task = self.prepare_task(config=self._get_config(location=temp),
                               build_graph=self.build_graph,
                               build_file_parser=self.build_file_parser)
      task.config_file
      self.assertEquals(temp, task.config_file)

  def test_no_section_in_pantsini(self):
    with self.assertRaises(TaskError):
      task = self.prepare_task(config=self._get_config(location=""),
                               build_graph=self.build_graph,
                               build_file_parser=self.build_file_parser)
      task.config_file

  def test_overriding_config_with_cli(self):
    with temporary_dir() as temp:
      task = self.prepare_task(config=self._get_config(section="bad-section-header"),
                               args=['--test-keystore-config-location={0}'.format(temp)],
                               build_graph=self.build_graph,
                               build_file_parser=self.build_file_parser)
      self.assertEquals(temp, task.config_file)

  def test_passing_empty_config_cli(self):
    with self.assertRaises(TaskError):
      task = self.prepare_task(args=['--test-keystore-config-location={0}'.format("")],
                               build_graph=self.build_graph,
                               build_file_parser=self.build_file_parser)
      task.config_file

  def test_render_args(self):
    with temporary_dir() as temp:
      with self.android_binary() as android_binary:
        task = self.prepare_task(config=self._get_config(),
                                   build_graph=self.build_graph,
                                   build_file_parser=self.build_file_parser)
        target = android_binary
        fake_key = self.FakeKeystore()
        task._dist = self.FakeDistribution()
        expected_args = ['path/to/jarsigner',
                         '-sigalg', 'SHA1withRSA', '-digestalg', 'SHA1',
                         '-keystore', '/path/to/key',
                         '-storepass', 'keystore_password',
                         '-keypass', 'key_password',
                         '-signedjar']
        expected_args.extend(['{0}/{1}.{2}.signed.apk'.format(temp, target.app_name,
                                                              fake_key.build_type)])
        expected_args.extend(['unsigned_apk_product', 'key_alias'])
        self.assertEquals(expected_args, task._render_args(target, fake_key, 'unsigned_apk_product',
                                                           temp))
