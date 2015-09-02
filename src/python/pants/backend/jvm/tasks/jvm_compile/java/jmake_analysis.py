# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (absolute_import, division, generators, nested_scopes, print_function,
                        unicode_literals, with_statement)

import os
from collections import defaultdict

from six.moves import range

from pants.backend.jvm.tasks.jvm_compile.analysis import Analysis
from pants.base.build_environment import get_buildroot


class JMakeAnalysis(Analysis):
  """Parsed representation of a jmake pdb.

  We use the term 'analysis' for uniformity with Zinc etc.
  """

  @classmethod
  def merge(cls, analyses):
    merged_pcd_entries = []
    merged_src_to_deps = {}
    for analysis in analyses:
      merged_pcd_entries.extend(analysis.pcd_entries)
      merged_src_to_deps.update(analysis.src_to_deps)
    return JMakeAnalysis(merged_pcd_entries, merged_src_to_deps)

  def __init__(self, pcd_entries, src_to_deps):
    self.pcd_entries = pcd_entries  # Note that second item in tuple is the source file.
    self.src_to_deps = src_to_deps

  def split(self, splits, catchall=False):
    buildroot = get_buildroot()
    src_to_split_idx = {}
    for i, split in enumerate(splits):
      for s in split:
        src_to_split_idx[s if os.path.isabs(s) else os.path.join(buildroot, s)] = i
    num_outputs = len(splits) + 1 if catchall else len(splits)
    catchall_idx = len(splits) if catchall else -1

    split_pcd_entries = []
    split_src_to_deps = []
    for _ in range(0, num_outputs):
      split_pcd_entries.append([])
      split_src_to_deps.append({})

    for pcd_entry in self.pcd_entries:
      split_idx = src_to_split_idx.get(pcd_entry[1], catchall_idx)
      if split_idx != -1:
        split_pcd_entries[split_idx].append(pcd_entry)
    for src, deps in self.src_to_deps.items():
      split_idx = src_to_split_idx.get(src, catchall_idx)
      if split_idx != -1:
        split_src_to_deps[split_idx][src] = deps

    return [JMakeAnalysis(x, y) for x, y in zip(split_pcd_entries, split_src_to_deps)]

  def write(self, outfile):
    # TODO: Profile and optimize this. For example, it can be faster to write in large chunks, even
    # at the cost of a large string join.
    outfile.write(b'pcd entries:\n')
    outfile.write(b'{} items\n'.format(len(self.pcd_entries)))
    for pcd_entry in self.pcd_entries:
      # Note that last element in pcd_entry already ends with a \n, so we don't write one.
      outfile.write(b'\t'.join(pcd_entry))

    outfile.write(b'dependencies:\n')
    outfile.write(b'{} items\n'.format(len(self.src_to_deps)))
    if os.environ.get('JMAKE_SORTED_ANALYSIS'):  # Useful in tests.
      lines = []
      for src, deps in self.src_to_deps.items():
        lines.append(b'{src}\t{deps}\n'.format(src=src, deps=b'\t'.join(deps)))
      for line in sorted(lines):
        outfile.write(line)
    else:
      for src, deps in self.src_to_deps.items():
        outfile.write(b'{src}\t{deps}\n'.format(src=src, deps=b'\t'.join(deps)))

  def compute_products(self):
    """Returns the products in this analysis.

    Returns a map of <src file full path> -> list of classfiles, relative to the classes dir.

    Note that we don't currently use this method: We use JMakeAnalysisParser.parse_products()
    to more efficiently read just the products out of the file. However we leave this
    here for documentation of the meaning of the useful fields in pcd_entries.
    """
    src_to_classfiles = defaultdict(list)
    for pcd_entry in self.pcd_entries:
      srcfile = pcd_entry[1]
      # In the file classes are represented with slashes, not dots. E.g., com/foo/bar/Baz.
      src_to_classfiles[srcfile].append(pcd_entry[0] + b'.class')
    return src_to_classfiles

  def is_equal_to(self, other):
    return (self.pcd_entries, self.src_to_deps) == (other.pcd_entries, other.src_to_deps)
