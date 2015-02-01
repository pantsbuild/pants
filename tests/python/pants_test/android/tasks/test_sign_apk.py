# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import textwrap

from pants.backend.android.targets.android_binary import AndroidBinary
from pants.backend.android.tasks.sign_apk import SignApkTask
from pants.base.build_file_aliases import BuildFileAliases
from pants.base.exceptions import TaskError
from pants.util.contextutil import temporary_dir, temporary_file
from pants_test.tasks.test_base import TaskTest


class SignApkTest(TaskTest):
  """Test the package signing methods in pants.backend.android.tasks."""

  _DEFAULT_KEYSTORE = '%(homedir)s/.doesnt/matter/keystore_config.ini'

  @classmethod
  def task_type(cls):
    return SignApkTask

  class FakeKeystore(object):
    # Mock keystores so as to test the render_args method.
    def __init__(self):
      self.build_type = 'debug'
      self.keystore_name = 'key_name'
      self.keystore_location = '/path/to/key'
      self.keystore_alias = 'key_alias'
      self.keystore_password = 'keystore_password'
      self.key_password = 'key_password'

  class FakeDistribution(object):
    # Mock JDK distribution so as to test the render_args method.
    @classmethod
    def binary(self, tool):
      return 'path/to/{0}'.format(tool)

  @property
  def alias_groups(self):
    return BuildFileAliases.create(targets={'android_binary': AndroidBinary})

  def _get_config(self,
                  section=SignApkTask._CONFIG_SECTION,
                  option='keystore_config_location',
                  location=_DEFAULT_KEYSTORE):
    ini = textwrap.dedent("""
    [{0}]

    {1}: {2}
    """).format(section, option, location)
    return ini

  def android_binary(self):
    with temporary_file() as fp:
      fp.write(textwrap.dedent(
      """<?xml version="1.0" encoding="utf-8"?>
      <manifest xmlns:android="http://schemas.android.com/apk/res/android"
          package="com.pants.examples.hello" >
          <uses-sdk
              android:minSdkVersion="8"
              android:targetSdkVersion="19" />
      </manifest>
      """))
      path = fp.name
      fp.close()
      target = self.make_target(spec=':binary',
                                target_type=AndroidBinary,
                                manifest=path)
      return target

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
      task = self.prepare_task(config=self._get_config(),
                               build_graph=self.build_graph,
                               build_file_parser=self.build_file_parser)
    target = self.android_binary()
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
    self.assertEquals(expected_args, task.render_args(target, fake_key, 'unsigned_apk_product',
                                                      temp))
