# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants_test.util.xml_test_base import XmlTestBase

from pants.contrib.android.android_manifest_parser import AndroidManifest, AndroidManifestParser


class TestAndroidManifestParser(XmlTestBase):
  """Test the AndroidManifestParser and AndroidManifest classes."""

  # Test AndroidManifestParser.parse_manifest().
  def test_parse_manifest(self):
    with self.xml_file() as xml:
      manifest = AndroidManifestParser.parse_manifest(xml)
      self.assertEqual(manifest.path, xml)

  def test_bad_parse_manifest(self):
    xml = '/no/file/here'
    with self.assertRaises(AndroidManifestParser.BadManifestError):
      AndroidManifestParser.parse_manifest(xml)

  # Test AndroidManifest.package_name.
  def test_package_name(self):
    with self.xml_file() as xml:
      manifest = AndroidManifestParser.parse_manifest(xml)
      self.assertEqual(manifest.package_name, 'org.pantsbuild.example.hello')

  def test_missing_manifest_element(self):
    with self.xml_file(manifest_element='some_other_element') as xml:
      with self.assertRaises(AndroidManifestParser.BadManifestError):
        AndroidManifestParser.parse_manifest(xml)

  def test_missing_package_attribute(self):
    with self.xml_file(package_attribute='bad_value') as xml:
      with self.assertRaises(AndroidManifestParser.BadManifestError):
        AndroidManifestParser.parse_manifest(xml)

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
      self.assertIsNone(manifest.target_sdk)

  def test_no_target_sdk_value(self):
    with self.xml_file(android_attribute='android:bad_value') as xml:
      parsed = AndroidManifestParser.parse_manifest(xml)
      self.assertIsNone(parsed.target_sdk)

  def test_no_android_part(self):
    with self.xml_file(android_attribute='unrelated:targetSdkVersion') as xml:
      manifest = AndroidManifestParser.parse_manifest(xml)
      self.assertEqual(manifest.package_name, 'org.pantsbuild.example.hello')

  def test_missing_whole_targetsdk(self):
    with self.xml_file(android_attribute='unrelated:cola') as xml:
      manifest = AndroidManifestParser.parse_manifest(xml)
      self.assertIsNone(manifest.target_sdk)

  # Test AndroidManifest().
  def test_android_manifest(self):
    with self.xml_file() as xml:
      test = AndroidManifest(xml, '19', 'com.foo.bar')
      self.assertEqual(test.path, xml)
