# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

from pants.base.deprecated import deprecated


@deprecated(removal_version='0.0.59', hint_message='Maven layout is now supported out of the box. '
                                                   'No special declarations neccessary.')
def maven_layout(parse_context, basedir=''):
  pass
