# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from xml.dom.minidom import parse


class XmlParser(object):
  """Parse .xml files."""

  class XmlError(Exception):
    """Raise when parsing the xml results in error."""

  @classmethod
  def _parse(cls, xml_path):
    """Parse .xml file and return parsed text as a DOM Document.

    :param string xml_path: File path of xml file to be parsed.
    :returns xml.dom.minidom.Document parsed_xml: Document instance containing parsed xml.
    """
    try:
      parsed_xml = parse(xml_path)
    # Minidom is a frontend for various parsers, only Exception covers ill-formed .xml for them all.
    except Exception as e:
      raise cls.XmlError('Error parsing xml file at {0}: {1}'.format(xml_path, e))
    return parsed_xml

  @classmethod
  def from_file(cls, xml_path):
    """Parse .xml file and create a XmlParser object."""
    try:
      parsed_xml = cls._parse(xml_path)
    except OSError as e:
      raise XmlParser.XmlError("Problem reading xml file at {}: {}".format(xml_path, e))
    return cls(xml_path, parsed_xml)

  def __init__(self, xml_path, parsed_xml):
    """XmlParser object.

    :param string xml_path: File path to original .xml file.
    :param xml.dom.minidom.Document parsed_xml: Document instance containing parsed xml.
    """
    self.xml_path = xml_path
    self.parsed = parsed_xml

  def get_attribute(self, element, attribute):
    """Retrieve the value of an attribute that is contained by the tag element.

    :param string element: Name of an xml element.
    :param string attribute: Name of the attribute that is to be returned.
    :return: Desired attribute value.
    :rtype: string
    """
    parsed_element = self.parsed.getElementsByTagName(element)
    if not parsed_element:
      raise self.XmlError("There is no '{0}' element in "
                          "xml file at: {1}".format(element, self.xml_path))
    parsed_attribute = parsed_element[0].getAttribute(attribute)
    if not parsed_attribute:
      raise self.XmlError("There is no '{0}' attribute in "
                          "xml at: {1}".format(attribute, self.xml_path))
    return parsed_attribute

  def get_optional_attribute(self, element, attribute):
    """Attempt to retrieve an optional attribute from the xml and return None on failure."""
    try:
      return self.get_attribute(element, attribute)
    except self.XmlError:
      return None
