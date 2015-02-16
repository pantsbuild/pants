# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.util.xml_parser import XmlParser


class AndroidManifestParser(XmlParser):
  """Parse AndroidManifest.xml and retrieve various elements and attributes.

  This class does not validate values, that is left to the consumers.
  """

  class BadManifestError(Exception):
    """Indicates an invalid android manifest due to missing elements."""

  @classmethod
  def get_package_name(cls, manifest):
    """Return the package name of the Android target as a string.

    :param AndroidManifestParser manifest: These objects hold already parsed .xml as
      AndroidManifestParser.parsed.
    :returns string: Package name from the AndroidManifest.xml.
    """
    manifest_element = manifest.parsed.getElementsByTagName('manifest')
    if not manifest_element:
      raise cls.BadManifestError("There is no 'manifest' element in "
                                 "manifest at: {0}".format(manifest.xml_path))
    package_name = manifest_element[0].getAttribute('package')
    if not package_name:
      raise cls.BadManifestError("There is no 'package' attribute in manifest "
                                 "at: {0}".format(manifest.xml_path))
    return package_name

  @classmethod
  def get_target_sdk(cls, manifest):
    """Return a string with the Android package's target SDK.

    :param AndroidManifestParser manifest: These objects hold already parsed .xml as
      AndroidManifestParser.parsed.
    :returns string: Target SDK version number from the AndroidManifest.xml.
    """
    sdk_element = manifest.parsed.getElementsByTagName('uses-sdk')
    if not sdk_element:
      raise cls.BadManifestError("There is no 'uses-sdk' element in "
                                 "manifest at: {0}".format(manifest.xml_path))
    target_sdk = sdk_element[0].getAttribute('android:targetSdkVersion')
    if not target_sdk:
      raise cls.BadManifestError("There is no 'android:targetSdkVersion' attribute in "
                                 "manifest at: {0}".format(manifest.xml_path))
    return target_sdk

  @classmethod
  def get_app_name(cls, manifest):
    """Return a string with the application name of the package or return None on failure.

    :param AndroidManifestParser manifest: These objects hold already parsed .xml as
      AndroidManifestParser.parsed.
    :returns string or None: Application name ('name' from foo.bar.name) or None if name not found.
    """
    activity_element = manifest.parsed.getElementsByTagName('activity')
    if activity_element:
      package_name = activity_element[0].getAttribute('android:name')
      if package_name:
        return package_name.split(".")[-1]
    return None
