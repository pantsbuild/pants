# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import textwrap
import unittest
from contextlib import contextmanager

from pants.backend.android.android_manifest_parser import AndroidManifestParser
from pants.util.contextutil import temporary_file


class TestAndroidManifestParser(unittest.TestCase):
  """Test the AndroidManifestParser class."""

  @contextmanager
  def android_manifest(self,
                       manifest_element='manifest',
                       package_attribute='package',
                       package_value='com.pants.examples.hello',
                       uses_sdk_element='uses-sdk',
                       android_attribute='android:targetSdkVersion',
                       activity_element='activity',
                       android_name_attribute='android:name',
                       package_name='com.pants.examples.hello.HelloWorld'):
    """Represent an AndroidManifest.xml."""
    with temporary_file() as fp:
      fp.write(textwrap.dedent(
        """<?xml version="1.0" encoding="utf-8"?>
        <{manifest} xmlns:android="http://schemas.android.com/apk/res/android"
            {package}="{package_name}" >
            <{uses_sdk}
                {android}="19" />
            <application >
                <{activity}
                    {android_name}="{package_name_value}" >
                </{activity}>
            </application>
        </{manifest}>""".format(manifest=manifest_element,
                                package=package_attribute,
                                package_name=package_value,
                                uses_sdk=uses_sdk_element,
                                android=android_attribute,
                                activity=activity_element,
                                android_name=android_name_attribute,
                                package_name_value=package_name)))
      fp.close()
      path = fp.name
      yield path

  # Test bad xml.
  def test_missing_attribute(self):
    # This catches the underlying xml exception and passes the error to the user.
    with self.assertRaises(AndroidManifestParser.BadManifestError):
      with self.android_manifest(package_attribute='') as manifest:
        self.assertEqual(AndroidManifestParser.get_package_name(manifest),
                         'com.pants.examples.hello')

  # Test AndroidManifestParser.get_package_name.
  def test_get_package_name(self):
    with self.android_manifest() as manifest:
      self.assertEqual(AndroidManifestParser.get_package_name(manifest),
                       'com.pants.examples.hello')

  def test_missing_manifest_element(self):
    with self.assertRaises(AndroidManifestParser.BadManifestError):
      with self.android_manifest(manifest_element='grape_soda') as manifest:
        self.assertEqual(AndroidManifestParser.get_package_name(manifest),
                         'com.pants.examples.hello')

  def test_missing_package_attribute(self):
    with self.assertRaises(AndroidManifestParser.BadManifestError):
      with self.android_manifest(package_attribute='bad_value') as manifest:
        self.assertEqual(AndroidManifestParser.get_package_name(manifest),
                         'com.pants.examples.hello')

  def test_weird_package_name(self):
      # Should accept unexpected package names, the info gets verified in classes that consume it.
    with self.android_manifest(package_value='cola') as manifest:
      self.assertEqual(AndroidManifestParser.get_package_name(manifest), 'cola')

  # Test AndroidManifestParser.get_target_sdk.
  def test_get_target_sdk(self):
    with self.android_manifest() as manifest:
      self.assertEqual(AndroidManifestParser.get_target_sdk(manifest), '19')

  def test_no_uses_sdk_element(self):
    with self.assertRaises(AndroidManifestParser.BadManifestError):
      with self.android_manifest(uses_sdk_element='something_random') as manifest:
        self.assertEqual(AndroidManifestParser.get_target_sdk(manifest), '19')

  def test_no_target_sdk_value(self):
    with self.assertRaises(AndroidManifestParser.BadManifestError):
      with self.android_manifest(android_attribute='android:bad_value') as manifest:
        self.assertEqual(AndroidManifestParser.get_target_sdk(manifest), '19')

  def test_no_android_part(self):
    with self.assertRaises(AndroidManifestParser.BadManifestError):
      with self.android_manifest(android_attribute='bad_value:targetSdkVersion') as manifest:
        self.assertEqual(AndroidManifestParser.get_target_sdk(manifest), '19')

  def test_missing_whole_targetsdk(self):
    with self.assertRaises(AndroidManifestParser.BadManifestError):
      with self.android_manifest(android_attribute='orange:cola') as manifest:
        self.assertEqual(AndroidManifestParser.get_target_sdk(manifest), '19')

  # Test AndroidManifestParser.get_app_name.
  def test_get_app_name(self):
    with self.android_manifest() as manifest:
      self.assertEqual(AndroidManifestParser.get_app_name(manifest), 'HelloWorld')

  def test_get_weird_app_name(self):
    with self.android_manifest(package_name='no_periods') as manifest:
      self.assertEqual(AndroidManifestParser.get_app_name(manifest), 'no_periods')

  # These last tests show AndroidManifestParser.get_app_name() fails silently and returns None.
  def test_no_activity_element(self):
    with self.android_manifest(activity_element='root_beer') as manifest:
      self.assertEqual(AndroidManifestParser.get_app_name(manifest), None)

  def test_no_android_name_attribute(self):
    with self.android_manifest(android_name_attribute='android:grape') as manifest:
      self.assertEqual(AndroidManifestParser.get_app_name(manifest), None)

  def test_no_app_name_matches(self):
    with self.android_manifest(android_name_attribute='no:match') as manifest:
      self.assertEqual(AndroidManifestParser.get_app_name(manifest), None)

  def test_bad_xml_app_name(self):
    with self.android_manifest(android_name_attribute='') as manifest:
      self.assertEqual(AndroidManifestParser.get_app_name(manifest), None)
