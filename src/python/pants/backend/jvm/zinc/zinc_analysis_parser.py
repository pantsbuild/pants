# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from collections import defaultdict

import six
from six.moves import range

from pants.backend.jvm.zinc.zinc_analysis import ZincAnalysis
from pants.backend.jvm.zinc.zinc_analysis_element_types import (APIs, Compilations, CompileSetup,
                                                                Relations, SourceInfos, Stamps)


class ZincAnalysisParser(object):
  """Parses a zinc analysis file."""

  class ParseError(Exception):
    pass

  def parse_from_path(self, infile_path):
    """Parse a ZincAnalysis instance from a text file."""
    with open(infile_path, 'rb') as infile:
      return self.parse(infile)

  def parse(self, infile):
    """Parse a ZincAnalysis instance from an open text file."""
    def parse_element(cls):
      parsed_sections = [self._parse_section(infile, header) for header in cls.headers]
      return cls(parsed_sections)

    self._verify_version(infile)
    compile_setup = parse_element(CompileSetup)
    relations = parse_element(Relations)
    stamps = parse_element(Stamps)
    apis = parse_element(APIs)
    source_infos = parse_element(SourceInfos)
    compilations = parse_element(Compilations)
    return ZincAnalysis(compile_setup, relations, stamps, apis, source_infos, compilations)

  def parse_products(self, infile):
    """An efficient parser of just the products section."""
    self._verify_version(infile)
    return self._find_repeated_at_header(infile, b'products')

  def parse_deps(self, infile, classes_dir):
    # Note: relies on the fact that these headers appear in this order in the file to use
    # the same file handle to read them mostly-sequentially.
    self._verify_version(infile)

    # Library dependencies: source -> jar.
    bin_deps = self._find_repeated_at_header(infile, b'library dependencies')
    # Class dependencies: classname -> classname.
    ext_deps = []
    for ext_dep_header in (b'member reference internal dependencies',
                           b'member reference external dependencies'):
      ext_deps.append(self._find_repeated_at_header(infile, ext_dep_header))

    classname_to_sources = {}
    for src, classnames in self._find_repeated_at_header(infile, b'class names').items():
      for classname in classnames:
        classname_to_sources[classname] = src

    # TODO(benjy): Temporary hack until we inject a dep on the scala runtime jar.
    scalalib_re = re.compile(r'scala-library-\d+\.\d+\.\d+\.jar$')
    filtered_bin_deps = defaultdict(list)
    for src, deps in six.iteritems(bin_deps):
      filtered_bin_deps[src] = filter(lambda x: scalalib_re.search(x) is None, deps)

    transformed_ext_deps = defaultdict(list)
    def fqcn_to_path(fqcn):
      return os.path.join(classes_dir, fqcn.replace(b'.', os.sep) + b'.class')
    for ext_deps_dict in ext_deps:
      for clz, fqcns in ext_deps_dict.items():
        transformed_ext_deps[classname_to_sources[clz]].extend(fqcn_to_path(fqcn) for fqcn in fqcns)

    # TODO: We skip converting the source classname to a target-internal sourcefile, although it
    # looks like we could do that by parsing the `class names` header from this section.
    ret = defaultdict(list)
    for d in [filtered_bin_deps, transformed_ext_deps]:
      for src, deps in d.items():
        ret[src].extend(deps)
    return ret

  def rebase_from_path(self, infile_path, outfile_path, rebase_mappings, java_home=None):
    with open(infile_path, 'rb') as infile:
      with open(outfile_path, 'wb') as outfile:
        self.rebase(infile, outfile, rebase_mappings, java_home)

  def rebase(self, infile, outfile, rebase_mappings, java_home=None):
    self._verify_version(infile)
    outfile.write(ZincAnalysis.FORMAT_VERSION_LINE)

    # Ensure we replace the longest match first, since the shorter one might be prefix of the longer.
    rebase_mappings_sorted = [(old_base, rebase_mappings[old_base])
                              for old_base in sorted(rebase_mappings, key=len, reverse=True)]
    def rebase_element(cls):
      for header in cls.headers:
        self._rebase_section(cls, header, infile, outfile, rebase_mappings_sorted, java_home)

    rebase_element(CompileSetup)
    rebase_element(Relations)
    rebase_element(Stamps)
    rebase_element(APIs)
    rebase_element(SourceInfos)
    rebase_element(Compilations)

  def _rebase_section(self, cls, header, lines_iter, outfile, rebase_mappings, java_home=None):
    # Booleans describing the rebasing logic to apply, if any.
    rebase_pants_home_anywhere = header in cls.pants_home_anywhere
    rebase_pants_home_prefix = header in cls.pants_home_prefix_only
    filter_java_home_anywhere = java_home and header in cls.java_home_anywhere
    filter_java_home_prefix = java_home and header in cls.java_home_prefix_only

    # Check the header and get the number of items.
    line = next(lines_iter)
    if header + b':\n' != line:
      raise self.ParseError('Expected: "{}:". Found: "{}"'.format(header, line))
    n = self._parse_num_items(next(lines_iter))

    # Iterate over the lines, applying rebasing/dropping logic as required.
    rebased_lines = []
    num_rebased_items = 0
    for _ in range(n):
      line = next(lines_iter)
      drop_line = ((filter_java_home_anywhere and java_home in line) or
                   (filter_java_home_prefix and line.startswith(java_home)))
      if not drop_line:
        rebased_line = line
        if rebase_pants_home_anywhere:
          for rebased_from, rebased_to in rebase_mappings:
            rebased_line = rebased_line.replace(rebased_from, rebased_to)
        elif rebase_pants_home_prefix:
          for rebased_from, rebased_to in rebase_mappings:
            if line.startswith(rebased_from):
              rebased_line = rebased_to + line[len(rebased_from):]
              break
        rebased_lines.append(rebased_line)
        num_rebased_items += 1
        if not cls.inline_vals:  # These values are blobs and never need to be rebased.
          rebased_lines.append(next(lines_iter))
      elif not cls.inline_vals:
        next(lines_iter)  # Also drop the non-inline value.

    # Write the rebased lines back out.
    outfile.write(header + b':\n')
    outfile.write(b'{} items\n'.format(num_rebased_items))
    chunk_size = 10000
    for i in range(0, len(rebased_lines), chunk_size):
      outfile.write(b''.join(rebased_lines[i:i+chunk_size]))

  def _find_repeated_at_header(self, lines_iter, header):
    header_line = header + b':\n'
    while next(lines_iter) != header_line:
      pass
    return self._parse_section(lines_iter, expected_header=None)

  def _verify_version(self, lines_iter):
    version_line = next(lines_iter)
    if version_line != ZincAnalysis.FORMAT_VERSION_LINE:
      raise self.ParseError('Unrecognized version line: ' + version_line)

  def _parse_section(self, lines_iter, expected_header=None):
    """Parse a single section."""
    if expected_header:
      line = next(lines_iter)
      if expected_header + b':\n' != line:
        raise self.ParseError('Expected: "{}:". Found: "{}"'.format(expected_header, line))
    n = self._parse_num_items(next(lines_iter))
    relation = defaultdict(list)  # Values are lists, to accommodate relations.
    for _ in range(n):
      k, _, v = next(lines_iter).partition(b' -> ')
      if len(v) == 1:  # Value on its own line.
        v = next(lines_iter)
      relation[k].append(v[:-1])
    return relation

  _num_items_re = re.compile(r'(\d+) items\n')

  def _parse_num_items(self, line):
    """Parse a line of the form '<num> items' and returns <num> as an int."""
    matchobj = self._num_items_re.match(line)
    if not matchobj:
      raise self.ParseError('Expected: "<num> items". Found: "{0}"'.format(line))
    return int(matchobj.group(1))
