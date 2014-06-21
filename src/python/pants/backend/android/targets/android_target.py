# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE)

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.payload import JvmTargetPayload
from pants.base.target import Target


class AndroidTarget(Target):
  """A base class for all Android targets"""

  def __init__(self,
               name=None,
               address=None,
               sources=None,
               sources_rel_path=None,
               excludes=None,
               provides=None,
               package=None,
               resources="res",
               # most recent build_tools_version should be defined elsewhere
               build_tools_version="19.1.0",
               target_sdk_version=None,
               min_sdk_version=None,
               release_type="debug",
               **kwargs):
    """
    :param name: target name
    :param sources: A list of filenames representing the source code.
    :type sources: list of strings
    :param excludes: One or more :class:`pants.targets.exclude.Exclude` instances
      to filter this target's transitive dependencies against.
    :param package: Package name of app, e.g. 'com.pants.examples.hello'
    :type package: string
    :param resources: name of directory containing the android resources. Set as 'res' by default.
    :param build_tools_version: Android API for the Build Tools (separate from SDK version). Default to latest available
    :param target_sdk_version: Version of the Android SDK the android target is built for
    :param min_sdk_version:  Earliest supported SDK by the android target
    :param release_type: Which keystore is used to sign target: 'debug' or 'release'. Set as 'debug' by default.
    """

    sources_rel_path = sources_rel_path or address.spec_path
    # No reasons why we might need AndroidPayload have presented themselves, which doesn't mean they won't come up later
    payload = JvmTargetPayload(sources=sources,
                               sources_rel_path=sources_rel_path,
                               provides=provides,
                               excludes=excludes)
    super(AndroidTarget, self).__init__(address=address, payload=payload, **kwargs)

    self.add_labels('android')
    self.build_tools_version = build_tools_version
    self.min_sdk_version = min_sdk_version
    self.package = package
    self.release_type = release_type
    self.resources = resources
    self.target_sdk_version = target_sdk_version
    #TODO write a manifest parser for the fields it can handle.