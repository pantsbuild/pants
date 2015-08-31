# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from six.moves import range

from pants.backend.jvm.tasks.jvm_compile.analysis_parser import AnalysisParser, ParseError
from pants.backend.jvm.tasks.jvm_compile.java.jmake_analysis import JMakeAnalysis
from pants.base.build_environment import get_buildroot


class JMakeAnalysisParser(AnalysisParser):
  """Parse a file containing representation of an analysis for some JVM language."""

  empty_test_header = b'pcd entries'
  current_test_header = b'pcd entries:\n'

  def parse(self, lines_iter):
    self._expect_header(next(lines_iter), 'pcd entries')
    num_pcd_entries = self.parse_num_items(next(lines_iter))
    pcd_entries = []
    for _ in range(0, num_pcd_entries):
      line = next(lines_iter)
      tpl = line.split(b'\t')
      if len(tpl) != 5:
        raise ParseError('Line must contain 5 tab-separated fields: {}'.format(line))
      pcd_entries.append(tpl)  # Note: we preserve the \n on the last entry.
    src_to_deps = self._parse_deps_at_position(lines_iter)
    return JMakeAnalysis(pcd_entries, src_to_deps)

  def parse_products(self, lines_iter, classes_dir):
    self._expect_header(next(lines_iter), b'pcd entries')
    num_pcd_entries = self.parse_num_items(next(lines_iter))
    ret = defaultdict(list)
    # Parse more efficiently than above, since we only care about
    # the first two elements in the line.
    for _ in range(0, num_pcd_entries):
      line = next(lines_iter)
      p1 = line.find(b'\t')
      clsfile = os.path.join(classes_dir, line[0:p1] + b'.class')
      p2 = line.find(b'\t', p1 + 1)
      src = line[p1 + 1:p2]
      ret[src].append(clsfile)
    return ret

  def parse_deps(self, lines_iter):
    buildroot = get_buildroot()
    self._expect_header(next(lines_iter), b'pcd entries')
    num_pcd_entries = self.parse_num_items(next(lines_iter))
    for _ in range(0, num_pcd_entries):
      next(lines_iter)  # Skip these lines.
    src_to_deps = self._parse_deps_at_position(lines_iter)
    ret = defaultdict(set)
    for src, deps in src_to_deps.items():
      for dep in deps:
        ret[src].add(dep + b'.class')
    return ret

  def rebase(self, lines_iter, outfile, pants_home_from, pants_home_to, java_home=None):
    # Note that jmake analysis contains no references to jars under java_home,
    # so we don't use that arg.
    # TODO: Profile and optimize this. For example, it can be faster to write in large chunks, even
    # at the cost of a large string join.
    self._expect_header(next(lines_iter), b'pcd entries')
    num_pcd_entries = self.parse_num_items(next(lines_iter))
    outfile.write(b'pcd entries:\n')
    outfile.write(b'{} items\n'.format(num_pcd_entries))
    for _ in range(num_pcd_entries):
      line = next(lines_iter)
      tpl = line.split(b'\t', 2)
      if tpl[1].startswith(pants_home_from):
        tpl[1] = pants_home_to + tpl[1][len(pants_home_from):]
      outfile.write(b'\t'.join(tpl))

    self._expect_header(next(lines_iter), b'dependencies')
    num_deps = self.parse_num_items(next(lines_iter))
    outfile.write(b'dependencies:\n')
    outfile.write(b'{} items\n'.format(num_deps))
    for _ in range(num_deps):
      line = next(lines_iter)
      if line.startswith(pants_home_from):
        line = pants_home_to + line[len(pants_home_from):]
      outfile.write(line)

  def _parse_deps_at_position(self, lines_iter):
    self._expect_header(next(lines_iter), b'dependencies')
    num_deps = self.parse_num_items(next(lines_iter))
    src_to_deps = {}
    for i in range(0, num_deps):
      tpl = next(lines_iter).split(b'\t')
      src = tpl[0]
      deps = tpl[1:]
      deps[-1] = deps[-1][0:-1]  # Trim off the \n.
      src_to_deps[src] = deps
    return src_to_deps

  def _expect_header(self, line, header):
    expected = header + b':\n'
    if line != expected:
      raise ParseError('Expected: {}. Found: {}'.format(expected, line))
