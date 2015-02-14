# coding=utf-8
# Copyright 2015 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from xml.dom.minidom import parse
from xml.parsers.expat import ExpatError


class AndroidManifestParser(object):
  """Parse an AndroidManifest.xml and retrieve elements from the xml. This class does
  not validate values, that is left to the consumers."""

  class BadManifestError(Exception):
    """Indicates an invalid android manifest due to ill-formed syntax or missing elements."""

  @classmethod
  def get_package_name(cls, manifest):
    """Return the package name of the Android target as a string."""
    try:
      manifest_element = parse(manifest).getElementsByTagName('manifest')
      if not manifest_element:
        raise cls.BadManifestError("There is no 'manifest' element in "
                                   "manifest at: {0}".format(manifest))
      package_name = manifest_element[0].getAttribute('package')
      if not package_name:
        raise cls.BadManifestError("There is no 'package' attribute in manifest "
                                   "at: {0}".format(manifest))
    except ExpatError as e:
      raise cls.BadManifestError("AndroidManifest at {0}: {1}".format(manifest, e))
    return package_name

  @classmethod
  def get_target_sdk(cls, manifest):
    """Return a string with the Android package's target SDK."""
    try:
      sdk_element = parse(manifest).getElementsByTagName('uses-sdk')
      if not sdk_element:
        raise cls.BadManifestError("There is no 'uses-sdk' element in "
                                   "manifest at: {0}".format(manifest))
      target_sdk = sdk_element[0].getAttribute('android:targetSdkVersion')
      # 'android:bad_value' returns an empty string so that must be explicitly checked.
      if not target_sdk:
        raise cls.BadManifestError("There is no 'android:targetSdkVersion' attribute in "
                                   "manifest at: {0}".format(manifest))
    except ExpatError as e:
      raise cls.BadManifestError('Problem with AndroidManifest at {0}: {1}'.format(manifest, e))
    return target_sdk

  @classmethod
  def get_app_name(cls, manifest):
    """Return a string with the application name of the package or return None on failure."""
    # Failure returns None and is handled by the consumer.
    try:
      activity_element = parse(manifest).getElementsByTagName('activity')
      package_name = activity_element[0].getAttribute('android:name')
      # The parser returns an empty string if it locates 'android' but cannot find 'name'.
      if package_name:
        return package_name.split(".")[-1]
      return None
    # We can swallow exceptions since this method has a fallback value.
    except:
      return None
