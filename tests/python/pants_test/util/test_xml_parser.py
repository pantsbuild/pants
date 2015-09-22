# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import textwrap
import unittest
from contextlib import contextmanager
from xml.dom.minidom import Document

from pants.util.contextutil import temporary_file
from pants.util.xml_parser import XmlParser


class TestXmlBase(unittest.TestCase):
  """Base class for tests that parse xml."""

  @contextmanager
  def xml_file(self,
               manifest_element='manifest',
               package_attribute='package',
               package_value='org.pantsbuild.example.hello',
               uses_sdk_element='uses-sdk',
               android_attribute='android:targetSdkVersion',
               activity_element='activity',
               android_name_attribute='android:name',
               application_name_value='org.pantsbuild.example.hello.HelloWorld'):
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


class TestXmlParser(TestXmlBase):
  """Test the XmlParser class."""

  def test_from_file(self):
    with self.xml_file() as xml:
      parser = XmlParser.from_file(xml)
      self.assertEqual(isinstance(parser, XmlParser), True)

  def test_bad_path(self):
    with self.assertRaises(XmlParser.XmlError):
      xml = '/no/file/here'
      XmlParser.from_file(xml)

  def test_parsed(self):
    with self.xml_file() as xml:
      parser = XmlParser.from_file(xml)
      self.assertEqual(isinstance(parser.parsed, Document), True)

  def test_xml_path(self):
    with self.xml_file() as xml:
      parser = XmlParser.from_file(xml)
      self.assertEqual(xml, parser.xml_path)

  def test_parse(self):
    with self.xml_file() as xml:
      parser = XmlParser.from_file(xml)
      self.assertEqual('manifest', parser.parsed.documentElement.tagName)

  # Test XmlParser.get_attribute().
  def test_get_attribute(self):
    with self.xml_file() as xml:
      parser = XmlParser.from_file(xml)
      self.assertEqual('org.pantsbuild.example.hello', parser.get_attribute('manifest', 'package'))

  def test_missing_attribute(self):
    with self.assertRaises(XmlParser.XmlError):
      with self.xml_file() as xml:
        parser = XmlParser.from_file(xml)
        self.assertEqual('not_present', parser.get_attribute('missing_attribute', 'package'))

  def test_missing_element(self):
    with self.assertRaises(XmlParser.XmlError):
      with self.xml_file() as xml:
        parser = XmlParser.from_file(xml)
        self.assertEqual('not_present', parser.get_attribute('manifest', 'missing_element'))

  # Test bad xml.
  def test_empty_attribute(self):
    with self.assertRaises(XmlParser.XmlError):
      with self.xml_file(package_attribute='') as xml:
        XmlParser.from_file(xml)

  def test_empty_element(self):
    with self.assertRaises(XmlParser.XmlError):
      with self.xml_file(manifest_element='') as xml:
        XmlParser.from_file(xml)

  def test_undeclared_element(self):
    with self.assertRaises(XmlParser.XmlError):
      with self.xml_file(android_name_attribute='undeclared:targetSdkVersion') as xml:
        XmlParser._parse(xml)
