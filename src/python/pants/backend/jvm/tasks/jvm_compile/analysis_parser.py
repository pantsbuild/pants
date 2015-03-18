# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from contextlib import contextmanager

from pants.base.exceptions import TaskError


class ParseError(TaskError):
  pass


@contextmanager
def raise_on_eof(infile):
  try:
    yield
  except StopIteration:
    filename = getattr(infile, 'name', None) or repr(infile)
    raise ParseError("Unexpected end-of-file parsing {0}".format(filename))


class AnalysisParser(object):
  """Parse a file containing representation of an analysis for some JVM language."""

  @property
  def empty_test_header(self):
    """The header of a section that will be nonempty iff the analysis is nonempty.

    We look at this section to determine whether the analysis contains any useful data.
    """
    raise NotImplementedError('Subclasses must implement.')

  def is_nonempty_analysis(self, path):
    """Does the specified analysis file contain information for at least one source file."""
    if not os.path.exists(path):
      return False
    with open(path, 'r') as infile:
      with raise_on_eof(infile):
        # Skip until we get to the section that will be nonempty iff the analysis is nonempty.
        expected_header = '{0}:\n'.format(self.empty_test_header)
        while infile.next() != expected_header:
          pass
        # Now see if this section is empty or not.
        return self.parse_num_items(infile.next()) > 0

  def parse_from_path(self, infile_path):
    """Parse an analysis instance from a text file."""
    with open(infile_path, 'r') as infile:
      return self.parse(infile)

  def parse(self, infile):
    """Parse an analysis instance from an open file."""
    raise NotImplementedError()

  def parse_products_from_path(self, infile_path, classes_dir):
    """An efficient parser of just the src->class mappings.

    Returns a map of src -> list of classfiles. All paths are absolute.
    """
    with open(infile_path, 'r') as infile:
      return self.parse_products(infile, classes_dir)

  def parse_products(self, infile, classes_dir):
    """An efficient parser of just the src->class mappings.

    Returns a map of src -> list of classfiles. All paths are absolute.
    """
    raise NotImplementedError()

  def parse_deps_from_path(self, infile_path, classpath_indexer, classes_dir):
    """An efficient parser of just the src->dep mappings.

    classpath_indexer - a no-arg method that an implementation may call if it needs a mapping
                        of class->element on the classpath that provides that class.
                        We use this indirection to avoid unnecessary precomputation.
    """
    with open(infile_path, 'r') as infile:
      return self.parse_deps(infile, classpath_indexer, classes_dir)

  def parse_deps(self, infile, classpath_indexer, classes_dir):
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
      raise ParseError('Expected: "<num> items". Found: "{0}"'.format(line))
    return int(matchobj.group(1))
