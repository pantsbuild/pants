# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.xml_parser import XmlParser


class AndroidManifestParser(object):
  """Parse AndroidManifest.xml and instantiate an AndroidManifest object to hold useful attributes.

  This class does not validate if the values are correct or useful, that is left to the consumers.
  """

  class BadManifestError(Exception):
    """Indicates an invalid android manifest."""

  @classmethod
  def parse_manifest(cls, manifest_path):
    """Parse the file at manifest_path and instantiate the AndroidManifestParser object.

    :param string manifest_path: File path that points to an xml file.
    :return: Object created from the parsed xml.
    :rtype: AndroidManifest
    """
    try:
      manifest = XmlParser.from_file(manifest_path)
      package_name = manifest.get_attribute('manifest', 'package')
    except XmlParser.XmlError as e:
      raise cls.BadManifestError("AndroidManifest.xml parsing error: {}".format(e))
    target_sdk = manifest.get_optional_attribute('uses-sdk', 'android:targetSdkVersion')

    return AndroidManifest(manifest.xml_path, target_sdk, package_name)


class AndroidManifest(object):
  """Object to represent an Android manifest."""

  def __init__(self, path, target_sdk, package_name):
    self.path = path
    self.target_sdk = target_sdk
    self.package_name = package_name
