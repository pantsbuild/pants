# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.backend.android.android_manifest_parser import AndroidManifest, AndroidManifestParser
from pants_test.util.test_xml_parser import TestXmlBase


class TestAndroidManifestParser(TestXmlBase):
  """Test the AndroidManifestParser and AndroidManifest classes."""

  # Test AndroidManifestParser.parse_manifest().
  def test_parse_manifest(self):
    with self.xml_file() as xml:
      manifest = AndroidManifestParser.parse_manifest(xml)
      self.assertEqual(manifest.path, xml)

  def test_bad_parse_manifest(self):
    with self.assertRaises(AndroidManifestParser.BadManifestError):
      xml = '/no/file/here'
      AndroidManifestParser.parse_manifest(xml)

  # Test AndroidManifest.package_name.
  def test_package_name(self):
    with self.xml_file() as xml:
      manifest = AndroidManifestParser.parse_manifest(xml)
      self.assertEqual(manifest.package_name, 'com.pants.examples.hello')

  def test_missing_manifest_element(self):
    with self.assertRaises(AndroidManifestParser.BadManifestError):
      with self.xml_file(manifest_element='some_other_element') as xml:
        manifest = AndroidManifestParser.parse_manifest(xml)
        self.assertEqual(manifest.package_name, 'com.pants.examples.hello')

  def test_missing_package_attribute(self):
    with self.assertRaises(AndroidManifestParser.BadManifestError):
      with self.xml_file(package_attribute='bad_value') as xml:
        manifest = AndroidManifestParser.parse_manifest(xml)
        self.assertEqual(manifest.package_name, 'com.pants.examples.hello')

  def test_weird_package_name(self):
    # Should accept unexpected package names, the info gets verified in classes that consume it.
    with self.xml_file(package_value='cola') as xml:
      manifest = AndroidManifestParser.parse_manifest(xml)
      self.assertEqual(manifest.package_name, 'cola')

  # Test AndroidManifest.target_sdk.
  def test_target_sdk(self):
    with self.xml_file() as xml:
      manifest = AndroidManifestParser.parse_manifest(xml)
      self.assertEqual(manifest.target_sdk, '19')

  # These next tests show AndroidManifest.target_sdk fails silently and returns None.
  def test_no_uses_sdk_element(self):
    with self.xml_file(uses_sdk_element='something-random') as xml:
      manifest = AndroidManifestParser.parse_manifest(xml)
      self.assertEqual(manifest.target_sdk, None)

  def test_no_target_sdk_value(self):
    with self.xml_file(android_attribute='android:bad_value') as xml:
      parsed = AndroidManifestParser.parse_manifest(xml)
      self.assertEqual(parsed.target_sdk, None)

  def test_no_android_part(self):
    with self.xml_file(android_attribute='unrelated:targetSdkVersion') as xml:
      manifest = AndroidManifestParser.parse_manifest(xml)
      self.assertEqual(manifest.target_sdk, None)

  def test_missing_whole_targetsdk(self):
    with self.xml_file(android_attribute='unrelated:cola') as xml:
      manifest = AndroidManifestParser.parse_manifest(xml)
      self.assertEqual(manifest.target_sdk, None)

  # Test AndroidManifest.app_name.
  def test_application_name(self):
    with self.xml_file() as xml:
      manifest = AndroidManifestParser.parse_manifest(xml)
      self.assertEqual(manifest.app_name, 'com.pants.examples.hello.HelloWorld')

  # These next tests show AndroidManifest.app_name fails silently and returns None.
  def test_no_activity_element(self):
    with self.xml_file(activity_element='root_beer') as xml:
      manifest = AndroidManifestParser.parse_manifest(xml)
      self.assertEqual(manifest.app_name, None)

  def test_no_android_name_attribute(self):
    with self.xml_file(android_name_attribute='android:grape') as xml:
      manifest = AndroidManifestParser.parse_manifest(xml)
      self.assertEqual(manifest.app_name, None)

  def test_no_attribute_tag_match(self):
    # With attribute:value, the attribute must be declared. We declare unrelated on ln 3 of the xml.
    with self.xml_file(android_name_attribute='unrelated:match') as xml:
      manifest = AndroidManifestParser.parse_manifest(xml)
      self.assertEqual(manifest.app_name, None)

  # Test AndroidManifest().
  def test_android_manifest(self):
    with self.xml_file() as xml:
      test = AndroidManifest(xml, '19', 'com.foo.bar', app_name='com.foo.bar.HelloBar')
      self.assertEqual(test.path, xml)

  def test_app_name_none(self):
    with self.xml_file() as xml:
      test = AndroidManifest(xml, '19', 'com.foo.bar', app_name=None)
      self.assertEqual(test.path, xml)

  def test_no_app_name(self):
    with self.xml_file() as xml:
      test = AndroidManifest(xml, '19', 'com.foo.bar')
      self.assertEqual(test.target_sdk, '19')
