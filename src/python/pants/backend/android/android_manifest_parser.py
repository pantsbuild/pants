# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.xml_parser import XmlParser


class AndroidManifestParser(XmlParser):
  """Parse AndroidManifest.xml and store needed values.

  This class does not validate values, that is left to the consumers.
  """

  class BadManifestError(Exception):
    """Indicates an invalid android manifest due to missing elements."""

  @classmethod
  def parse_manifest(cls, manifest_path):
    """Parse the file at manifest_path and instantiate the AndroidManifestParser object.

    :param string manifest_path: File path that points to an xml file.
    :return: Object created from the parsed xml.
    :rtype: AndroidManifestParser
    """
    manifest = cls._parse(manifest_path)
    return cls(manifest_path, manifest)

  def __init__(self, manifest_path, parsed_manifest):
    super(AndroidManifestParser, self).__init__(manifest_path, parsed_manifest)
    self._target_sdk = None
    self._package_name = None
    self._app_name = None

  @property
  def package_name(self,):
    """Return the package name of the Android target as a string.

    :return: Package name from the AndroidManifest.xml.
    :rtype: string
    """
    if self._package_name is None:
      self._package_name = self.get_android_attribute('manifest', 'package')
    return self._package_name

  @property
  def target_sdk(self):
    """Return a string with the Android package's target SDK.

    :return: Target SDK version number from the AndroidManifest.xml.
    :rtype: string
    """
    if self._target_sdk is None:
      self._target_sdk = self.get_android_attribute('uses-sdk', 'android:targetSdkVersion')
    return self._target_sdk

  @property
  def application_name(self):
    """Return a string with the application name of the package or return None on failure.

    :return: Application name ('name' from foo.bar.name) or None if name not found.
    :rtype: string or None
    """
    # Use android.target.app_name to get the application name, it provides a fallback value.
    if self._app_name is None:
      try:
        app_name = self.get_android_attribute('activity', 'android:name')
        self._app_name = app_name.split(".")[-1]
      except self.BadManifestError:
        self._app_name = None
    return self._app_name

  def get_android_attribute(self, element, attribute):
    """Get attribute from parsed xml and raise self.BadManifestError upon failure.

    :param element: The xml element that surrounds the required attribute.
    :param attribute: The xml attribute that is returned by the method.
    :return: Value of the attribute from the xml.
    :rtype: string
    """
    try:
      attribute = self.get_attribute(element, attribute)
    except XmlParser.XmlError as e:
      raise self.BadManifestError("AndroidManifest.xml parsing error: {}".format(e))
    return attribute
