# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)


class Analysis(object):
  """Parsed representation of an analysis for some JVM language.

  An analysis provides information on the src -> class product mappings
  and on the src -> {src|class|jar} file dependency mappings.
  """
  @classmethod
  def merge(cls, analyses):
    """Merge multiple analysis instances into one."""
    raise NotImplementedError()

  def split(self, splits, catchall=False):
    """Split the analysis according to splits, which is a list of K iterables of source files.

    If catchall is False, returns a list of K ZincAnalysis objects, one for each of the splits, in order.
    If catchall is True, returns K+1 ZincAnalysis objects, the last one containing the analysis for any
    remainder sources not mentioned in the K splits.
    """
    raise NotImplementedError()

  def write_to_path(self, outfile_path, rebasings=None):
    with open(outfile_path, 'w') as outfile:
      self.write(outfile, rebasings)

  def write(self, outfile, rebasings=None):
    """Write this Analysis to outfile.

    rebasings: A list of path prefix pairs [from_prefix, to_prefix] to rewrite.
               to_prefix may be None, in which case matching paths are removed entirely.
    """
    raise NotImplementedError()
