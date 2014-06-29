# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE)

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.base.build_manual import manual
from pants.backend.android.targets.android_target import AndroidTarget


@manual.builddict(tags=['android'])
class AndroidBinary(AndroidTarget):
  """Produces an Android binary."""

  def __init__(self, *args, **kwargs):
    """
    :param string name: The name of this target, which combined with this
      build file defines the :doc:`target address <target_addresses>`.
    :param sources: Source code files to compile. Paths are relative to the
      BUILD file's directory.
    :type sources: ``Fileset`` or list of strings.
    :param excludes: List of :ref:`exclude <bdict_exclude>`\s
      to filter this target's transitive dependencies against.
    :param package: Package name of app, e.g. 'com.pants.examples.hello'
    :type package: string
    :param resources: name of directory containing the android resources. Set as 'res' by default.
    :param build_tools_version: API for the Build Tools (separate from SDK version).
      Defaults to the latest full release.
    :param target_sdk_version: Version of the Android SDK the android target is built for
    :param min_sdk_version:  Earliest supported SDK by the android target
    :param release_type: Which keystore is used to sign target: 'debug' or 'release'.
      Set as 'debug' by default.
    """

    # TODO (mateor): Add some Compatibility error checks.
    super(AndroidBinary, self).__init__(*args, **kwargs)
