# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import six

from pants.backend.jvm.tasks.jvm_compile.analysis import Analysis
from pants.backend.jvm.zinc.zinc_analysis import ZincAnalysis as UnderlyingAnalysis


class ZincAnalysis(Analysis):
  """Parsed representation of a zinc analysis.

  Implemented by delegating to an underlying pants.backend.jvm.zinc.ZincAnalysis instance.

  Note also that all files in keys/values are full-path, just as they appear in the analysis file.
  If you want paths relative to the build root or the classes dir or whatever, you must compute
  those yourself.
  """

  FORMAT_VERSION_LINE = UnderlyingAnalysis.FORMAT_VERSION_LINE

  def __init__(self, underlying_analysis):
    self._underlying_analysis = underlying_analysis

  @property
  def underlying_analysis(self):
    return self._underlying_analysis

  def write(self, outfile):
    self.underlying_analysis.write(outfile)

  def __eq__(self, other):
    if other is None:
      return False
    return self.underlying_analysis == other.underlying_analysis

  def __ne__(self, other):
    return not self.__eq__(other)

  def __hash__(self):
    return hash(self.underlying_analysis)

  def __str__(self):
    return str(self.underlying_analysis)

  def __unicode__(self):
    return six.text_type(self.underlying_analysis)
