# coding=utf-8
# Copyright 2014 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import (nested_scopes, generators, division, absolute_import, with_statement,
                        print_function, unicode_literals)

import os
from collections import defaultdict

from pants.base.build_environment import get_buildroot
from pants.backend.jvm.tasks.jvm_compile.analysis import Analysis


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
    for _ in xrange(0, num_outputs):
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

  def write(self, outfile, rebasings=None):
    # Note that the only paths in a jmake analysis are source files.
    def rebase_path(path):
      if rebasings:
        for rebase_from, rebase_to in rebasings:
          if rebase_to is None:
            if path.startswith(rebase_from):
              return None
          else:
            path = path.replace(rebase_from, rebase_to)
      return path

    outfile.write('pcd entries:\n')
    outfile.write('%d items\n' % len(self.pcd_entries))
    for pcd_entry in self.pcd_entries:
      rebased_src = rebase_path(pcd_entry[1])
      if rebased_src:
        outfile.write(pcd_entry[0])
        outfile.write('\t')
        outfile.write(rebased_src)
        for x in pcd_entry[2:]:
          outfile.write('\t')
          outfile.write(x)
          # Note that last element already includes \n.

    outfile.write('dependencies:\n')
    outfile.write('%d items\n' % len(self.src_to_deps))
    for src, deps in self.src_to_deps.items():
      rebased_src = rebase_path(src)
      if rebased_src:
        outfile.write(rebased_src)
        for dep in deps:
          outfile.write('\t')
          outfile.write(dep)
        outfile.write('\n')

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
      src_to_classfiles[srcfile].append(pcd_entry[0] + '.class')
    return src_to_classfiles
