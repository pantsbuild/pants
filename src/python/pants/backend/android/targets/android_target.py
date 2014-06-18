# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.target import Target

class AndroidTarget(Target):
  """A base class for all Android targets"""

  def __init__(self,
               name=None,
               address=None,
               sources=None,
               sources_rel_path=None,
               excludes=None,
               manifest="AndroidManifest.xml",
               package=None,
               resources="res",
               # build_tools_version default should be defined in ini
               build_tools_version="19.1.0",
               target_sdk_version=None,
               min_sdk_version=None,
               platform_target=None,
               keystore="debug",
               **kwargs):
      """
      :param name:
      :param address:
      :param sources:
      :param sources_rel_path: #TODO: Use? Used in payload for Jvm
      :param excludes:
      :param manifest: Name of the android manifest (required by tooling to be named AndroidManifest.xml)
      :param package: Package name of app as string: 'com.pants.examples.hello' #TODO fill w/ manifest parser.
      :param resources:
      :param build_tools_version: Android API for the Build Tools (separate from SDK version) Default to latest
      :param target_sdk_version: Version of the Android SDK the android target is built for
      :param min_sdk_version:  Earliest supported SDK by the android target
      :param platform_target: which Google API to use, e.g. "17" or "19"
      :param keystore: 'debug' or 'release' TODO: Set 'debug as default'
       :return:
      """
      self.add_labels('android')
      self.build_tools_version = build_tools_version
      self.release_type = keystore
      self.resources = resources
      self.package = package
      self.target_sdk_version = target_sdk_version
      #TODO manifest parser for the fields it can handle.
