# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE)

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

from pants.backend.android.targets.android_target import AndroidTarget


class AndroidBinary(AndroidTarget):

  def __init__(self,
               name,
               sources,
               provides=None,
               dependencies=None,
               excludes=None,
               **kwargs):

    # TODO: Add some Compatibility error checks.
    super(AndroidBinary, self).__init__(name=name, sources=sources, **kwargs)
