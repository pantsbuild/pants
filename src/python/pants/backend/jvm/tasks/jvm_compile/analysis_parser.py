# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re

from pants.base.exceptions import TaskError


class ParseError(TaskError):
  pass


class AnalysisParser(object):
  """Parse a file containing representation of an analysis for some JVM language."""

  def __init__(self, classes_dir):
    self.classes_dir = classes_dir  # The output dir for classes in this analysis.

  @property
  def empty_test_header(self):
    """The header of a section that will be empty iff the analysis is trivial."""
    raise NotImplementedError('Subclasses must implement.')

  def is_nonempty_analysis(self, path):
    """Returns whether an analysis at a specified path is nontrivial."""
    if not os.path.exists(path):
      return False
    with open(path, 'r') as infile:
      while infile.next() != '{0}:\n'.format(self.empty_test_header):
        pass
      return self.parse_num_items(infile) > 0

  def empty_prefix(self):
    """Returns a prefix indicating a trivial analysis file.

    I.e., this prefix is present at the begnning of an analysis file iff the analysis is trivial.
    """
    raise NotImplementedError()

  def parse_from_path(self, infile_path):
    """Parse an analysis instance from a text file."""
    with open(infile_path, 'r') as infile:
      return self.parse(infile)

  def parse(self, infile):
    """Parse an analysis instance from an open file."""
    raise NotImplementedError()

  def parse_products_from_path(self, infile_path):
    """An efficient parser of just the src->class mappings.

    Returns a map of src -> list of classfiles. All paths are absolute.
    """
    with open(infile_path, 'r') as infile:
      return self.parse_products(infile)

  def parse_products(self, infile):
    """An efficient parser of just the src->class mappings.

    Returns a map of src -> list of classfiles. All paths are absolute.
    """
    raise NotImplementedError()

  def parse_deps_from_path(self, infile_path, classpath_indexer):
    """An efficient parser of just the src->dep mappings.

    classpath_indexer - a no-arg method that an implementation may call if it needs a mapping
                        of class->element on the classpath that provides that class.
                        We use this indirection to avoid unnecessary precomputation.
    """
    with open(infile_path, 'r') as infile:
      return self.parse_deps(infile, classpath_indexer)

  def parse_deps(self, infile, classpath_indexer):
    """An efficient parser of just the binary, source and external deps sections.

    classpath_indexer - a no-arg method that an implementation may call if it needs a mapping
                        of class->element on the classpath that provides that class.
                        We use this indirection to avoid unnecessary precomputation.

    Returns a dict of src -> iterable of deps, where each item in deps is either a binary dep,
    source dep or external dep, i.e., either a source file, a class file or a jar file.

    All paths are absolute.
    """
    raise NotImplementedError()

  _num_items_re = re.compile(r'(\d+) items\n')

  def parse_num_items(self, line):
    """Parse a line of the form '<num> items' and returns <num> as an int."""
    matchobj = self._num_items_re.match(line)
    if not matchobj:
      raise ParseError('Expected: "<num> items". Found: "%s"' % line)
    return int(matchobj.group(1))
