# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from xml.dom.minidom import parse


class XmlParser(object):
  """Parse .xml files."""

  class BadXmlException(Exception):
    """Raise when parsing the xml results in error."""

  @classmethod
  def _parse(cls, xml_path):
    """Parse .xml file.

    Use this class method to create XmlParser instances.
    :param string xml_path: File path of xml file to be parsed.
    :returns xml.dom.minidom.Document parsed_xml: Document instance containing parsed xml.
    """
    try:
      parsed_xml = parse(xml_path)
    # Minidom is a frontend for various parsers, only Exception covers ill-formed .xml for them all.
    except Exception as e:
      raise cls.BadXmlException('Error parsing xml: {}'.format(e))
    return parsed_xml

  @classmethod
  def from_file(cls, xml_path):
    """Parse .xml file and create a XmlParser object."""
    parsed_xml = cls._parse(xml_path)
    return cls(xml_path, parsed_xml)

  def __init__(self, xml_path, parsed_xml):
    """XmlParser object.

    :param string xml_path: File path to original .xml file.
    :param xml.dom.minidom.Document parsed_xml: Document instance containing parsed xml.
    """
    self.xml_path = xml_path
    self.parsed = parsed_xml
