# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
import re
from collections import defaultdict

from pants.base.build_environment import get_buildroot
from pants.backend.jvm.tasks.jvm_compile.analysis_parser import AnalysisParser, ParseError
from pants.backend.jvm.tasks.jvm_compile.java.jmake_analysis import JMakeAnalysis


class JMakeAnalysisParser(AnalysisParser):
  """Parse a file containing representation of an analysis for some JVM language."""

  def empty_prefix(self):
    return 'pcd entries:\n0 items\n'

  def parse(self, infile):
    self._expect_header(infile.readline(), 'pcd entries')
    num_pcd_entries = self._parse_num_items(infile.readline())
    pcd_entries = []
    for i in xrange(0, num_pcd_entries):
      line = infile.readline()
      tpl = line.split('\t')
      if len(tpl) != 5:
        raise ParseError('Line must contain 5 tab-separated fields: %s' % line)
      pcd_entries.append(tpl)  # Note: we preserve the \n on the last entry.
    src_to_deps = self._parse_deps_at_position(infile)
    return JMakeAnalysis(pcd_entries, src_to_deps)

  def parse_products(self, infile):
    self._expect_header(infile.readline(), 'pcd entries')
    num_pcd_entries = self._parse_num_items(infile.readline())
    ret = defaultdict(list)
    # Parse more efficiently than above, since we only care about
    # the first two elements in the line.
    for _ in xrange(0, num_pcd_entries):
      line = infile.readline()
      p1 = line.find('\t')
      clsfile = os.path.join(self.classes_dir, line[0:p1] + '.class')
      p2 = line.find('\t', p1 + 1)
      src = line[p1+1:p2]
      ret[src].append(clsfile)
    return ret

  def parse_deps(self, infile, classpath_indexer):
    buildroot = get_buildroot()
    classpath_elements_by_class = classpath_indexer()
    self._expect_header(infile.readline(), 'pcd entries')
    num_pcd_entries = self._parse_num_items(infile.readline())
    for _ in xrange(0, num_pcd_entries):
      infile.readline()  # Skip these lines.
    src_to_deps = self._parse_deps_at_position(infile)
    ret = defaultdict(set)
    for src, deps in src_to_deps.items():
      for dep in deps:
        rel_classfile = dep + '.class'
        # Check if we have an internal class first.
        internal_classfile = os.path.join(buildroot, self.classes_dir, rel_classfile)
        if os.path.exists(internal_classfile):
          # Dep is on an internal class.
          ret[src].add(internal_classfile)
        elif rel_classfile in classpath_elements_by_class:
          # Dep is on an external jar/classes dir.
          ret[src].add(classpath_elements_by_class.get(rel_classfile))

    return ret

  def _parse_deps_at_position(self, infile):
    self._expect_header(infile.readline(), 'dependencies')
    num_deps = self._parse_num_items(infile.readline())
    src_to_deps = {}
    for i in xrange(0, num_deps):
      tpl = infile.readline().split('\t')
      src = tpl[0]
      deps = tpl[1:]
      deps[-1] = deps[-1][0:-1]  # Trim off the \n.
      src_to_deps[src] = deps
    return src_to_deps

  num_items_re = re.compile(r'(\d+) items\n')

  def _parse_num_items(self, line):
    """Parse a line of the form '<num> items' and returns <num> as an int."""
    matchobj = JMakeAnalysisParser.num_items_re.match(line)
    if not matchobj:
      raise ParseError('Expected: "<num> items". Found: "%s"' % line)
    return int(matchobj.group(1))

  def _expect_header(self, line, header):
    expected = header + ':\n'
    if line != expected:
      raise ParseError('Expected: %s. Found: %s' % (expected, line))
