# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os

import six
from zincutils.zinc_analysis import ZincAnalysis as UnderlyingAnalysis

from pants.backend.jvm.tasks.jvm_compile.analysis import Analysis
from pants.base.build_environment import get_buildroot


class ZincAnalysis(Analysis):
  """Parsed representation of a zinc analysis.

  Implemented by delegating to an underlying zincutils.ZincAnalysis instance.

  Note also that all files in keys/values are full-path, just as they appear in the analysis file.
  If you want paths relative to the build root or the classes dir or whatever, you must compute
  those yourself.

  zincutils code is at https://github.com/pantsbuild/zincutils.
  See its README on how to publish it.

  To run a dev pants against zincutils sources, without having to publish, just add its root dir
  to your PYTHONPATH, e.g.:

   PYTHONPATH=/path/to/zincutils/ \
    ./pants test tests/python/pants_test/backend/jvm/tasks/jvm_compile/scala:zinc_analysis
  """

  FORMAT_VERSION_LINE = UnderlyingAnalysis.FORMAT_VERSION_LINE

  @classmethod
  def merge(cls, analyses):
    return ZincAnalysis(UnderlyingAnalysis.merge([a._underlying_analysis for a in analyses]))

  def __init__(self, underlying_analysis):
    self._underlying_analysis = underlying_analysis

  @property
  def underlying_analysis(self):
    return self._underlying_analysis

  def sources(self):
    return self._underlying_analysis.sources()

  def split(self, splits, catchall=False):
    buildroot = get_buildroot()
    abs_splits = [set([s if os.path.isabs(s) else os.path.join(buildroot, s) for s in x])
                  for x in splits]
    return [ZincAnalysis(s) for s in self.underlying_analysis.split(abs_splits, catchall)]

  def write(self, outfile):
    self.underlying_analysis.write(outfile)

  def diff(self, other):
    return self.underlying_analysis.diff(other.underlying_analysis)

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
