# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
import re
from collections import defaultdict

from six.moves import range

from pants.backend.jvm.tasks.jvm_compile.analysis_parser import (AnalysisParser, ParseError,
                                                                 raise_on_eof)
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis import (APIs, Compilations,
                                                                     CompileSetup, Relations,
                                                                     SourceInfos, Stamps,
                                                                     ZincAnalysis)


class ZincAnalysisParser(AnalysisParser):
  """Parses a zinc analysis file."""

  empty_test_header = 'products'
  current_test_header = ZincAnalysis.FORMAT_VERSION_LINE

  def parse(self, infile):
    """Parse a ZincAnalysis instance from an open text file."""
    def parse_element(cls):
      parsed_sections = [self._parse_section(infile, header) for header in cls.headers]
      return cls(parsed_sections)

    with raise_on_eof(infile):
      self._verify_version(infile)
      compile_setup = parse_element(CompileSetup)
      relations = parse_element(Relations)
      stamps = parse_element(Stamps)
      apis = parse_element(APIs)
      source_infos = parse_element(SourceInfos)
      compilations = parse_element(Compilations)
      return ZincAnalysis(compile_setup, relations, stamps, apis, source_infos, compilations)

  def parse_products(self, infile, classes_dir):
    """An efficient parser of just the products section."""
    with raise_on_eof(infile):
      self._verify_version(infile)
      return self._find_repeated_at_header(infile, 'products')

  def parse_deps(self, infile, classpath_indexer, classes_dir):
    with raise_on_eof(infile):
      self._verify_version(infile)
      # Note: relies on the fact that these headers appear in this order in the file.
      bin_deps = self._find_repeated_at_header(infile, 'binary dependencies')
      src_deps = self._find_repeated_at_header(infile, 'direct source dependencies')
      ext_deps = self._find_repeated_at_header(infile, 'direct external dependencies')

    # TODO(benjy): Temporary hack until we inject a dep on the scala runtime jar.
    scalalib_re = re.compile(r'scala-library-\d+\.\d+\.\d+\.jar$')
    filtered_bin_deps = defaultdict(list)
    for src, deps in bin_deps.iteritems():
      filtered_bin_deps[src] = filter(lambda x: scalalib_re.search(x) is None, deps)

    transformed_ext_deps = {}
    def fqcn_to_path(fqcn):
      return os.path.join(classes_dir, fqcn.replace('.', os.sep) + '.class')
    for src, fqcns in ext_deps.items():
      transformed_ext_deps[src] = [fqcn_to_path(fqcn) for fqcn in fqcns]

    ret = defaultdict(list)
    for d in [filtered_bin_deps, src_deps, transformed_ext_deps]:
      ret.update(d)
    return ret

  def _find_repeated_at_header(self, lines_iter, header):
    header_line = header + ':\n'
    while lines_iter.next() != header_line:
      pass
    return self._parse_section(lines_iter, expected_header=None)

  def _verify_version(self, lines_iter):
    version_line = lines_iter.next()
    if version_line != ZincAnalysis.FORMAT_VERSION_LINE:
      raise ParseError('Unrecognized version line: ' + version_line)

  def _parse_section(self, lines_iter, expected_header=None):
    """Parse a single section."""
    if expected_header:
      line = lines_iter.next()
      if expected_header + ':\n' != line:
        raise ParseError('Expected: "{}:". Found: "{}"'.format(expected_header, line))
    n = self.parse_num_items(lines_iter.next())
    relation = defaultdict(list)  # Values are lists, to accommodate relations.
    for i in range(n):
      k, _, v = lines_iter.next().decode('utf-8').partition(' -> ')
      if len(v) == 1:  # Value on its own line.
        v = lines_iter.next()
      relation[k].append(v[:-1])
    return relation
