# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).


from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import textwrap
import unittest
from contextlib import contextmanager
from xml.dom.minidom import Document

from pants.util.xml_parser import XmlParser
from pants.util.contextutil import temporary_file


class TestXmlParser(unittest.TestCase):
  """Test the XmlParser class."""

  @contextmanager
  def xml_file(self,
               manifest_element='manifest',
               package_attribute='package',
               package_value='com.pants.examples.hello',
               uses_sdk_element='uses-sdk',
               android_attribute='android:targetSdkVersion',
               activity_element='activity',
               android_name_attribute='android:name',
               application_name_value='com.pants.examples.hello.HelloWorld'):
    """Represent an .xml file (Here an AndroidManifest.xml is used)."""
    with temporary_file() as fp:
      fp.write(textwrap.dedent(
        """<?xml version="1.0" encoding="utf-8"?>
        <{manifest} xmlns:android="http://schemas.android.com/apk/res/android"
                    xmlns:unrelated="http://schemas.android.com/apk/res/android"
            {package}="{package_name}" >
            <{uses_sdk}
                {android}="19" />
            <application >
                <{activity}
                    {android_name}="{application_name}" >
                </{activity}>
            </application>
        </{manifest}>""".format(manifest=manifest_element,
                                package=package_attribute,
                                package_name=package_value,
                                uses_sdk=uses_sdk_element,
                                android=android_attribute,
                                activity=activity_element,
                                android_name=android_name_attribute,
                                application_name=application_name_value)))
      fp.close()
      path = fp.name
      yield path


  def test_from_file(self):
    with self.xml_file() as manifest:
      parser = XmlParser.from_file(manifest)
      self.assertEqual(isinstance(parser, XmlParser), True)

  def test_parsed(self):
    with self.xml_file() as manifest:
      parser = XmlParser.from_file(manifest)
      self.assertEqual(isinstance(parser.parsed, Document), True)

  def test_xml_path(self):
    with self.xml_file() as manifest:
      parser = XmlParser.from_file(manifest)
      self.assertEqual(manifest, parser.xml_path)

  def test_parse(self):
    with self.xml_file() as manifest:
      parser = XmlParser.from_file(manifest)
      self.assertEqual('manifest', parser.parsed.documentElement.tagName)

  # Test bad xml.
  def test_missing_attribute(self):
    with self.assertRaises(XmlParser.BadXmlException):
      with self.xml_file(package_attribute='') as manifest:
        XmlParser.from_file(manifest)

  def test_missing_element(self):
    with self.assertRaises(XmlParser.BadXmlException):
      with self.xml_file(manifest_element='') as manifest:
        XmlParser.from_file(manifest)

  def test_undeclared_element(self):
    with self.assertRaises(XmlParser.BadXmlException):
      with self.xml_file(android_name_attribute='undeclared:targetSdkVersion') as manifest:
        XmlParser._parse(manifest)
