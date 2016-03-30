# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from xml.dom.minidom import Document

from pants.util.xml_parser import XmlParser
from pants_test.util.xml_test_base import XmlTestBase


class TestXmlParser(XmlTestBase):
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
