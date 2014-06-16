# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import json
import os
import re
from collections import defaultdict

from pants.backend.jvm.tasks.jvm_compile.analysis_parser import AnalysisParser, ParseError
from pants.backend.jvm.tasks.jvm_compile.scala.zinc_analysis import APIs, Compilations, CompileSetup, Relations, SourceInfos, Stamps, ZincAnalysis


class ZincAnalysisParser(AnalysisParser):
  """Parses a zinc analysis file."""

  def empty_prefix(self):
    return 'products:\n0 items\n'

  def parse(self, infile):
    """Parse a ZincAnalysis instance from an open text file."""
    def parse_element(cls):
      parsed_sections = [self._parse_section(infile, header) for header in cls.headers]
      return cls(parsed_sections)

    self._verify_version(infile)
    relations = parse_element(Relations)
    stamps = parse_element(Stamps)
    apis = parse_element(APIs)
    source_infos = parse_element(SourceInfos)
    compilations = parse_element(Compilations)
    compile_setup = parse_element(CompileSetup)
    return ZincAnalysis(relations, stamps, apis, source_infos, compilations, compile_setup)

  def parse_products(self, infile):
    """An efficient parser of just the products section."""
    self._verify_version(infile)
    return self._find_repeated_at_header(infile, 'products')

  def parse_deps(self, infile, classpath_indexer):
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
      return os.path.join(self.classes_dir, fqcn.replace('.', os.sep) + '.class')
    for src, fqcns in ext_deps.items():
      transformed_ext_deps[src] = [fqcn_to_path(fqcn) for fqcn in fqcns]

    ret = defaultdict(list)
    for d in [filtered_bin_deps, src_deps, transformed_ext_deps]:
      ret.update(d)
    return ret

  # Extra zinc-specific methods re json.

  def parse_json_from_path(self, infile_path):
    """Parse a ZincAnalysis instance from a JSON file."""
    with open(infile_path, 'r') as infile:
      return self.parse_from_json(infile)

  def parse_from_json(self, infile):
    """Parse a ZincAnalysis instance from an open JSON file."""
    obj = json.load(infile)
    relations = Relations.from_json_obj(obj['relations'])
    stamps = Stamps.from_json_obj(obj['stamps'])
    apis = APIs.from_json_obj(obj['apis'])
    source_infos = SourceInfos.from_json_obj(obj['source infos'])
    compilations = Compilations.from_json_obj(obj['compilations'])
    compile_setup = Compilations.from_json_obj(obj['compile setup'])
    return ZincAnalysis(relations, stamps, apis, source_infos, compilations, compile_setup)

  def _find_repeated_at_header(self, lines_iter, header):
    header_line = header + ':\n'
    while lines_iter.next() != header_line:
      pass
    return self._parse_section(lines_iter, expected_header=None)

  def _verify_version(self, lines_iter):
    version_line = lines_iter.next()
    if version_line != ZincAnalysis.FORMAT_VERSION_LINE:
      raise ParseError('Unrecognized version line: ' + version_line)

  _num_items_re = re.compile(r'(\d+) items\n')

  def _parse_num_items(self, lines_iter):
    """Parse a line of the form '<num> items' and returns <num> as an int."""
    line = lines_iter.next()
    matchobj = self._num_items_re.match(line)
    if not matchobj:
      raise ParseError('Expected: "<num> items". Found: "%s"' % line)
    return int(matchobj.group(1))

  def _parse_section(self, lines_iter, expected_header=None):
    """Parse a single section."""
    if expected_header:
      line = lines_iter.next()
      if expected_header + ':\n' != line:
        raise ParseError('Expected: "%s:". Found: "%s"' % (expected_header, line))
    n = self._parse_num_items(lines_iter)
    relation = defaultdict(list)  # Values are lists, to accommodate relations.
    for i in xrange(n):
      k, _, v = lines_iter.next().partition(' -> ')
      if len(v) == 1:  # Value on its own line.
        v = lines_iter.next()
      relation[k].append(v[:-1])
    return relation
