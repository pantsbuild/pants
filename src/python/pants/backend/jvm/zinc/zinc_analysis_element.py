# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

import six


class ZincAnalysisElement(object):
  """Encapsulates one part of a Zinc analysis.

  Zinc analysis files are text files consisting of sections. Each section is introduced by
  a header, followed by lines of the form K -> V, where the same K may repeat multiple times.

  For example, the 'products:' section maps source files to the class files it produces, e.g.,

  products:
  123 items
  org/pantsbuild/Foo.scala -> org/pantsbuild/Foo.class
  org/pantsbuild/Foo.scala -> org/pantsbuild/Foo$.class
  ...

  Related consecutive sections are bundled together in "elements". E.g., the Stamps element
  bundles the section for source file stamps, the section for jar file stamps etc.

  An instance of this class represents such an element.
  """
  # Whether values in this element are written inline, i.e., key -> val, or not, i.e., key -> \nval.
  inline_vals = True

  # The section names for the sections in this element. Subclasses override.
  headers = ()

  # The following are tuples of section names in this element to which different forms of rebasing
  # logic apply. Subclasses may override to have rebasing logic applied appropriately to the
  # relevant section. This makes rebasing far more efficient than blindly string-replacing
  # everywhere.

  # Sections that can reference paths under the pants home anywhere on a line.
  # To rebase pants home we must string-replace anywhere in the line.
  pants_home_anywhere = ()

  # Sections that can reference paths under the pants home, but only at the beginning of a line.
  # To rebase pants home we can just check the prefix.
  pants_home_prefix_only = ()

  # Sections that can reference paths under the jvm home anywhere on a line.
  # To filter out lines with jvm home references we must search the entire line.
  java_home_anywhere = ()

  # Sections that can reference paths under the jvm home, but only at the beginning of a line.
  # To filter out lines with jvm home references we need check the prefix.
  java_home_prefix_only = ()

  def __init__(self, args, always_sort=False):
    """
    :param args: A list of maps from key to list of values.
    :param always_sort: If True, sections are always sorted. Otherwise they are only sorted
                        if the environment variable ZINCUTILS_SORTED_ANALYSIS is set.

    Each map in ``args`` corresponds to a section in the analysis file. E.g.,

    'org/pantsbuild/Foo.scala': ['org/pantsbuild/Foo.class', 'org/pantsbuild/Foo$.class']

    Subclasses can alias the elements of self.args in their own __init__, for convenience.
    """
    self._always_sort = always_sort
    if self.should_be_sorted():
      self.args = []
      for arg in args:
        sorted_arg = defaultdict(list)
        for k, vs in arg.items():
          sorted_arg[k] = sorted(vs)
        self.args.append(sorted_arg)
    else:
      self.args = args

  def should_be_sorted(self):
    return self._always_sort or os.environ.get('ZINCUTILS_SORTED_ANALYSIS')

  def is_equal_to(self, other):
    # Is sensitive to ordering of keys and vals. Will NOT WORK as expected unless
    # should_be_sorted() returns True for both self and other.  So only call this
    # in tests, where you're guaranteeing that sorting.
    return self.args == other.args

  def write(self, outfile):
    self._write_multiple_sections(outfile, self.headers, self.args)

  def _write_multiple_sections(self, outfile, headers, reps):
    """Write multiple sections."""
    for header, rep in zip(headers, reps):
      self._write_section(outfile, header, rep)

  def _write_section(self, outfile, header, rep):
    """Write a single section.

    Items are sorted, for ease of testing, only if ZINCUTILS_SORTED_ANALYSIS is set in
    the environment, and is not falsy. The sort is too costly to have in production use.
    """
    num_items = sum(len(vals) for vals in six.itervalues(rep))

    outfile.write(header + b':\n')
    outfile.write(b'{} items\n'.format(num_items))

    # Writing in large chunks is significantly faster than writing line-by-line.
    fragments = []
    def do_write():
      buf = b''.join(fragments)
      outfile.write(buf)
      del fragments[:]

    if self.should_be_sorted():
      # Write everything in a single chunk, so we can sort.
      for k, vals in six.iteritems(rep):
        for v in vals:
          item = b'{} -> {}{}\n'.format(k, b'' if self.inline_vals else b'\n', v)
          fragments.append(item)
      fragments.sort()
      do_write()
    else:
      # It's not strictly necessary to chunk on item boundaries, but it's nicer.
      chunk_size = 40000 if self.inline_vals else 50000
      for k, vals in six.iteritems(rep):
        for v in vals:
          fragments.append(k)
          fragments.append(b' -> ')
          if not self.inline_vals:
            fragments.append(b'\n')
          fragments.append(v)
          fragments.append(b'\n')
        if len(fragments) >= chunk_size:
          do_write()
      do_write()

  def translate_keys(self, token_translator, arg):
    old_keys = list(six.iterkeys(arg))
    for k in old_keys:
      vals = arg[k]
      del arg[k]
      arg[token_translator.convert(k)] = vals

  def translate_values(self, token_translator, arg):
    for k, vals in six.iteritems(arg):
      arg[k] = [token_translator.convert(v) for v in vals]

  def translate_base64_values(self, token_translator, arg):
    for k, vals in six.iteritems(arg):
      arg[k] = [token_translator.convert_base64_string(v) for v in vals]
