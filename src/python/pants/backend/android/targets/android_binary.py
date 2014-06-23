# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE)

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.android.targets.android_target import AndroidTarget


class AndroidBinary(AndroidTarget):
  """Produces an Android binary."""

  def __init__(self,
               name=None,
               sources=None,
               provides=None,
               dependencies=None,
               excludes=None,
               **kwargs):
    """
   :param string name: The name of this target, which combined with this
      build file defines the target :class:`pants.base.address.Address`.
    :param sources: A list of filenames representing the source code.
    :type sources: list of strings
    :param excludes: One or more :class:`pants.targets.exclude.Exclude` instances
      to filter this target's transitive dependencies against.
    :param package: Package name of app, e.g. 'com.pants.examples.hello'
    :type package: string
    :param resources: name of directory containing the android resources. Set as 'res' by default.
    :param build_tools_version: API for the Build Tools (separate from SDK version).
      Default to latest available
    :param target_sdk_version: Version of the Android SDK the android target is built for
    :param min_sdk_version:  Earliest supported SDK by the android target
    :param release_type: Which keystore is used to sign target: 'debug' or 'release'.
      Set as 'debug' by default.
    """

    # TODO: Add some Compatibility error checks.
    super(AndroidBinary, self).__init__(name=name, sources=sources, **kwargs)
